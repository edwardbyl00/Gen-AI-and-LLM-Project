"""Execution, validation and paired evaluation regressions without paid calls."""

import csv
import json
from types import SimpleNamespace

import pytest

from agents.supervisor import ablation
from agents.supervisor.checks import safe_route, valid_tasks
from agents.supervisor.pipeline import handle_question
from agents.supervisor.router import ROUTING_SCHEMA, route_question
from agents.supervisor.synthesis import build_context


def task(name, agent, question):
    return {"id": name, "agent": agent, "question": question,
            "required_elements": ["Requested fact"]}


def routing(tasks, route="both"):
    return {"route": route, "answerable": True, "check_premise": False,
            "reason": "Needs evidence", "tasks": tasks}


def synth(bundle):
    return {"answer": "Supported answer", "declined": False, "sources": [], "cited": []}


@pytest.mark.parametrize("bad", [
    routing([task("x", "price", "q"), task("x", "policy", "q")]),
    routing([task("x", "price", "q")]),
    routing([task("x", "unknown", "q")], route="price"),
    routing([task("x", "price", " ")], route="price"),
    routing([task(str(i), "price", "q") for i in range(7)], route="price"),
])
def test_invalid_task_plans_are_retried_and_fall_back(bad):
    calls = []
    def router(q, **kwargs):
        calls.append(q)
        return bad
    record, events = safe_route("q", router=router, decompose=True)
    assert len(calls) == 2
    assert record["route"] == "none" and record["tasks"] == []
    assert valid_tasks(record)
    assert all(e["code"] == "malformed_tasks" for e in events)


def test_same_router_call_uses_separate_schema_without_mutating_baseline():
    requests = []
    plan = routing([task("p", "price", "prices"), task("h", "policy", "grants")])
    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(plan)))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    assert route_question("original", client=client, decompose=True)["tasks"] == plan["tasks"]
    assert len(requests) == 1
    assert "tasks" in requests[0]["response_format"]["json_schema"]["schema"]["required"]
    assert "tasks" not in ROUTING_SCHEMA["schema"]["properties"]


def test_focused_tasks_multiple_prices_and_abstention_reach_synthesis():
    tasks = [task("a", "price", "Tampines prices in 2023"),
             task("b", "price", "Bedok prices in 2023"),
             task("c", "policy", "First-time resale grants")]
    calls = []
    def price(q, today, usage_log):
        calls.append(q)
        usage_log.append({"step": "price_filters", "input_tokens": 10, "output_tokens": 2})
        return {"town": q.split()[0], "mean_price": 500000, "n_deals": 20}
    def policy(q, today, usage_log):
        calls.append(q)
        return {"decision": "ABSTAIN", "reason": "Missing rules", "evidence": []}
    def synthesis(bundle):
        text, passages = build_context(bundle)
        assert "Tampines" in text and "Bedok" in text
        assert "First-time resale grants" in text and "Missing rules" in text
        assert passages == []
        return synth(bundle)
    bundle = handle_question("Original mixed question", decompose=True,
        route_fn=lambda q, **kw: (routing(tasks), []), price_fn=price, policy_fn=policy,
        synth_fn=synthesis)
    assert calls == [t["question"] for t in tasks]
    assert [u["task_id"] for u in bundle["usage"]] == ["a", "b"]
    assert len(bundle["task_results"]) == 3
    assert bundle["variant"] == "B_decomposition"


def test_failed_task_does_not_erase_other_results():
    def price(q, today, usage_log):
        if q == "bad":
            raise RuntimeError("unavailable")
        return {"n_deals": 1}
    bundle = handle_question("q", decompose=True,
        route_fn=lambda q, **kw: (routing([task("bad", "price", "bad"),
                                          task("good", "price", "good")], "price"), []),
        price_fn=price, synth_fn=synth)
    assert "bad" in bundle["agent_errors"]
    assert bundle["task_results"][1]["result"]["n_deals"] == 1


def test_question_loader_excludes_reference_answers_and_rejects_duplicates(tmp_path):
    path = tmp_path / "unseen.csv"
    path.write_text('question_id,question,category,gold_answer\nU1,Question?,mixed,SECRET\n')
    assert ablation.load_questions(path) == [
        {"question_id": "U1", "question": "Question?", "category": "mixed"}]
    path.write_text('question_id,question\nU1,one\nU1,two\n')
    with pytest.raises(ValueError):
        ablation.load_questions(path)


def test_paired_runner_blinding_scoring_and_failure_accounting(tmp_path):
    seen = []
    def answer(q, today, decompose, usage_log):
        seen.append((q, today, decompose))
        if decompose and q == "Broken?":
            raise RuntimeError("test failure")
        return {"answer": synth({}), "routing": {"route": "price"}, "agent_errors": {},
                "usage": [{"step": "policy_assessor", "calls": 2, "input_tokens": 100, "output_tokens": 10}],
                "steps": [], "cost_usd": 0.001}
    questions = [{"question_id": "U1", "question": "Good?", "category": "mixed"},
                 {"question_id": "U2", "question": "Broken?", "category": "price"}]
    out = tmp_path / "experiment"
    records = ablation.run_experiment(questions, out, "2026-10-28", repeats=2, answer_fn=answer)
    assert len(records) == len(seen) == 8
    assert all(day == "2026-10-28" for _, day, _ in seen)
    assert sum(bool(r["error"]) for r in records) == 2
    assert all(r["model_calls"] == 2 for r in records if not r["error"])
    with (out / "grading_blind.csv").open() as f:
        grades = list(csv.DictReader(f))
    assert "variant" not in grades[0] and "repeat" not in grades[0]
    assert all(not g["correctness"] for g in grades)
    with pytest.raises(ValueError, match="Missing/invalid"):
        ablation.score_experiment(out, out / "grading_blind.csv")
    for g in grades:
        for metric in ablation.GRADES:
            g[metric] = "0" if g["answer"] == "[Pipeline execution failed]" else "1"
    ablation.write_csv(out / "graded.csv", grades, list(grades[0]))
    scores = ablation.score_experiment(out, out / "graded.csv")
    assert scores["paired_B_minus_A"]["correctness"] == {"n_pairs": 4, "mean": -0.5}
    b = next(s for s in scores["efficiency"] if s["variant"] == "B_decomposition" and s["group"] == "all")
    assert b["pipeline_errors"] == b["usage_incomplete_runs"] == 2
    assert b["runs"] == 4
    with pytest.raises(FileExistsError):
        ablation.run_experiment(questions, out, "2026-10-28", answer_fn=answer)
    # Even a fully graded subset must not be mistaken for a complete experiment.
    lines = (out / "runs.jsonl").read_text().splitlines()
    (out / "runs.jsonl").write_text("\n".join(lines[:-1]) + "\n")
    with pytest.raises(ValueError, match="Incomplete"):
        ablation.score_experiment(out, out / "graded.csv")


def test_routing_exception_retains_reported_tokens(tmp_path):
    def failing_answer(q, today, decompose, usage_log):
        def failing_router(q, **kwargs):
            kwargs["usage_log"].append({"step": "router", "input_tokens": 100, "output_tokens": 10})
            raise RuntimeError("unrecoverable router error")
        return handle_question(q, today=today, decompose=decompose, route_fn=failing_router,
                               usage_log=usage_log)
    records = ablation.run_experiment(
        [{"question_id": "q", "question": "question", "category": "mixed"}],
        tmp_path / "failed", "2026-10-28", answer_fn=failing_answer)
    assert all(r["input_tokens"] == 100 and r["output_tokens"] == 10 for r in records)
    assert all(r["cost_usd"] > 0 and r["usage_incomplete"] for r in records)
