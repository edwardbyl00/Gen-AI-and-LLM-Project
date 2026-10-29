"""P3 regression tests for mixed questions, task retries and accounting; no APIs."""

import json

import pytest

from agents.graph.graph import build_graph, run
from agents.supervisor import ablation, tasks as task_module
from agents.supervisor.pipeline import handle_question
from agents.supervisor.synthesis import build_context

QUESTION = "Since singles can't buy resale flats, what's the cheapest 2-room in Yishun?"
POLICY_QUESTION = "Is the claim that singles cannot buy HDB resale flats correct? What conditions apply?"
PRICE_QUESTION = "What is the lowest recorded resale price of a 2-room flat in Yishun?"
TASKS = [
    {"id": "price_1", "agent": "price", "question": PRICE_QUESTION,
     "required_elements": ["Minimum recorded resale price", "Period", "Transaction count"]},
    {"id": "policy_1", "agent": "policy", "question": POLICY_QUESTION,
     "required_elements": ["Verify singles resale eligibility claim"]},
]
PASSAGE = {"chunk_id": "fixture_eligibility", "title": "Fixture eligibility",
           "url": "https://example.invalid/policy", "text": "Eligible singles may buy resale flats."}
POLICY = {"decision": "ANSWER_READY", "reason": "Premise can be checked", "evidence": [PASSAGE]}
PRICE = {"town": "YISHUN", "flat_type": "2 ROOM", "min_price": 318000,
         "period_start": "2025-10", "period_end": "2026-09", "n_deals": 54}
SETTINGS = {"max_retries": 1, "llm_check": False}


def router_for(tasks=TASKS, route="both"):
    calls = []
    def route_fn(question, today=None, usage_log=None, decompose=False):
        calls.append((question, decompose))
        usage_log.append({"step": "router", "input_tokens": 10, "output_tokens": 5})
        record = {"route": route, "check_premise": True, "answerable": True, "reason": "Check claim and prices"}
        if decompose:
            record["tasks"] = tasks
        return record, []
    route_fn.calls = calls
    return route_fn


class Agent:
    def __init__(self, result, step, calls=1):
        self.result, self.step, self.count, self.questions = result, step, calls, []

    def __call__(self, question, today, usage_log=None):
        self.questions.append(question)
        usage_log.append({"step": self.step, "calls": self.count,
                          "input_tokens": 100, "output_tokens": 10})
        return self.result


def synthesis(bundle, usage_log=None):
    context, passages = build_context(bundle)
    usage_log.append({"step": "synthesis", "input_tokens": 20, "output_tokens": 5})
    return {"answer": "Fixture answer", "declined": False,
            "cited": list(range(1, len(passages) + 1)), "sources": [], "events": []}


def test_mixed_question_uses_supervisor_tasks_once_and_logs_policy_calls():
    router = router_for()
    price, policy = Agent(PRICE, "price_filters"), Agent(POLICY, "policy_assessor", calls=2)
    seen = []
    def synth(bundle, usage_log=None):
        seen.append(bundle)
        return synthesis(bundle, usage_log)
    collector = []
    app = build_graph(router, price, policy, synth, self_check_settings=SETTINGS, decompose=True)
    state = run(QUESTION, app=app, usage_log=collector)
    assert router.calls == [(QUESTION, True)]
    assert price.questions == [PRICE_QUESTION] and policy.questions == [POLICY_QUESTION]
    assert state["question"] == QUESTION and state["variant"] == "B_decomposition"
    assert [r["task"]["id"] for r in state["task_results"]] == ["price_1", "policy_1"]
    assert all(r["error"] is None for r in state["task_results"])
    assert state["self_check"]["verdict"] == "pass"
    assert len(seen) == 1 and seen[0]["task_results"] == state["task_results"]
    policy_usage = next(u for u in state["usage"] if u["step"] == "policy_assessor")
    assert policy_usage["task_id"] == "policy_1" and policy_usage["calls"] == 2
    assert sum(u.get("calls", 1) for u in collector) == 5
    assert collector == state["usage"] and state["cost_usd"] > 0


def test_config_true_is_read_by_both_entry_points_and_false_override_works(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text("supervisor:\n  decompose: true\n")
    monkeypatch.setattr(task_module, "CONFIG_FILE", config)
    router = router_for()
    policy, price = Agent(POLICY, "policy_assessor"), Agent(PRICE, "price_filters")
    app = build_graph(router, price, policy, synthesis, self_check_settings=SETTINGS)
    assert run(QUESTION, app=app)["decompose"] is True
    handle_question(QUESTION, route_fn=router, price_fn=price, policy_fn=policy,
                    synth_fn=lambda bundle: {"answer": "fixture", "declined": True})
    state = run(QUESTION, app=app, decompose=False)
    assert router.calls == [(QUESTION, True), (QUESTION, True), (QUESTION, False)]
    assert "task_results" not in state and state["variant"] == "A_baseline"
    assert price.questions[-1] == policy.questions[-1] == QUESTION


def test_retry_only_failed_task_keeps_successful_siblings_and_focused_question():
    extra = {**TASKS[1], "id": "policy_2", "question": "Which resale eligibility conditions apply?"}
    router = router_for(TASKS + [extra])
    seen = []
    def policy(question, today, usage_log=None):
        seen.append(question)
        usage_log.append({"step": "policy_assessor", "input_tokens": 10, "output_tokens": 2})
        if question == extra["question"] and seen.count(question) == 1:
            raise RuntimeError("temporary failure")
        return POLICY
    price = Agent(PRICE, "price_filters")
    states = []
    def synth(bundle, usage_log=None):
        states.append(bundle)
        return synthesis(bundle, usage_log)
    state = run(QUESTION, app=build_graph(router, price, policy, synth,
                                         self_check_settings=SETTINGS), decompose=True)
    assert router.calls == [(QUESTION, True)]
    assert price.questions == [PRICE_QUESTION]
    assert seen == [POLICY_QUESTION, extra["question"], extra["question"]]
    assert state["agent_errors"] == {} and state["attempts"] == 1
    assert len(state["task_results"]) == 3
    assert len(states) == 2 and states[0]["task_results"][2]["error"]
    assert state["task_results"][2]["error"] is None
    assert [r["attempt"] for r in state["task_results"]] == [1, 1, 2]
    calls = [u for u in state["usage"] if u.get("task_id") == "policy_2"]
    assert [u["attempt"] for u in calls] == [1, 2]


def test_parallel_failed_branches_recover_without_duplicate_synthesis():
    counts = {"price": 0, "policy": 0}
    def agent(name, result):
        def call(question, today, usage_log=None):
            counts[name] += 1
            if counts[name] == 1:
                raise RuntimeError(name + " failed")
            return result
        return call
    state = run(QUESTION, decompose=True, app=build_graph(router_for(),
        agent("price", PRICE), agent("policy", POLICY), synthesis, self_check_settings=SETTINGS))
    assert counts == {"price": 2, "policy": 2} and state["agent_errors"] == {}
    assert len([s for s in state["steps"] if s["step"] == "synthesis"]) == 2
    assert len(state["task_results"]) == 2


def test_self_check_sees_evidence_from_later_policy_task():
    tasks = [TASKS[1], {**TASKS[1], "id": "policy_2", "question": "Other eligibility question"}]
    def policy(question, today, usage_log=None):
        return {"decision": "ABSTAIN", "evidence": []} if question == POLICY_QUESTION else POLICY
    def uncited(bundle, usage_log=None):
        return {"answer": "No citations", "declined": False, "cited": [], "events": []}
    state = run(QUESTION, decompose=True, app=build_graph(
        router_for(tasks, route="policy"), Agent(PRICE, "price_filters"), policy, uncited,
        self_check_settings=SETTINGS))
    assert state["self_check"]["verdict"] == "weak"
    assert state["self_check"]["problems"][0]["rule"] == "A2"
    assert state["attempts"] == 1


def test_synthesis_retry_retains_tasks_and_does_not_call_router_again():
    router = router_for()
    price, policy = Agent(PRICE, "price_filters"), Agent(POLICY, "policy_assessor")
    reviews = []
    def check(state, usage_log=None):
        reviews.append(state)
        return {"weak": len(reviews) == 1, "problems": [
            {"rule": "A1", "issue": "Clarify claim", "target": "synthesis"}]} if len(reviews) == 1 else {"weak": False, "problems": []}
    state = run(QUESTION, decompose=True, app=build_graph(router, price, policy, synthesis,
        check_fn=check, self_check_settings={"max_retries": 1, "llm_check": True}))
    assert len(router.calls) == len(price.questions) == len(policy.questions) == 1
    assert len(reviews) == 2 and reviews[0]["task_results"] == reviews[1]["task_results"]
    assert state["question"] == QUESTION


def test_invalid_task_plan_does_not_reach_agents():
    price = Agent(PRICE, "price_filters")
    with pytest.raises(ValueError, match="invalid tasks"):
        run(QUESTION, decompose=True, app=build_graph(router_for([], route="both"), price,
            Agent(POLICY, "policy_assessor"), synthesis, self_check_settings=SETTINGS))
    assert not price.questions


def test_graph_ablation_selects_p3_and_records_its_scope(tmp_path, monkeypatch):
    assert ablation.select_pipeline("graph") is run
    calls = []
    def fake_graph(question, today, decompose, usage_log):
        calls.append(decompose)
        app = build_graph(router_for(), Agent(PRICE, "price_filters"),
                          Agent(POLICY, "policy_assessor"), synthesis, self_check_settings=SETTINGS)
        return run(question, today=today, decompose=decompose, app=app, usage_log=usage_log)
    monkeypatch.setattr(ablation, "select_pipeline", lambda name: fake_graph if name == "graph" else None)
    records = ablation.run_experiment([{"question_id": "fixture", "question": QUESTION, "category": "mixed"}],
                                      tmp_path / "graph", "2026-10-29", pipeline="graph")
    assert sorted(calls) == [False, True]
    assert all(r["error"] is None and not r["usage_incomplete"] for r in records)
    manifest = json.loads((tmp_path / "graph/manifest.json").read_text())
    assert manifest["pipeline"] == "graph" and "self-check" in manifest["scope"]
    assert manifest["config"]["self_check"]


@pytest.mark.parametrize("route, selected", [("price", {"price"}),
                                            ("policy", {"policy"}), ("none", set())])
def test_decomposed_single_source_and_no_source_routes(route, selected):
    plan = [t for t in TASKS if t["agent"] in selected]
    router = router_for(plan, route=route)
    price, policy = Agent(PRICE, "price_filters"), Agent(POLICY, "policy_assessor")
    state = run(QUESTION, decompose=True, app=build_graph(router, price, policy,
        synthesis, self_check_settings=SETTINGS))
    assert bool(price.questions) == ("price" in selected)
    assert bool(policy.questions) == ("policy" in selected)
    assert len(state["task_results"]) == len(plan)
    assert len([s for s in state["steps"] if s["step"] == "synthesis"]) == 1


def test_failed_router_retains_reported_usage_in_external_collector():
    collector = []
    def failing_router(q, **kwargs):
        kwargs["usage_log"].append({"step": "router", "input_tokens": 10, "output_tokens": 1})
        raise RuntimeError("unavailable")
    app = build_graph(failing_router, Agent(PRICE, "price_filters"),
        Agent(POLICY, "policy_assessor"), synthesis,
        self_check_settings=SETTINGS, usage_log=collector)
    with pytest.raises(RuntimeError, match="unavailable"):
        run(QUESTION, app=app, decompose=True)
    assert collector == [{"step": "router", "input_tokens": 10, "output_tokens": 1}]
