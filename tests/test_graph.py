"""Tests for the LangGraph pipeline (no API calls)."""

import pytest

from agents.graph.graph import build_graph, run
from agents.supervisor.adapters import get_policy_agent


def fake_route(record, events=None, usage=None):
    """A fake safe_route that records what it was called with."""
    calls = []
    def route(question, today=None, usage_log=None):
        calls.append((question, today))
        if usage_log is not None and usage:
            usage_log.append(usage)
        return dict(record), list(events or [])
    route.calls = calls
    return route


class Spy:
    """A fake agent that remembers whether it was called. Like P1's price
    agent, it accepts an optional usage_log and can add a usage entry to it."""
    def __init__(self, result=None, error=None, usage=None):
        self.calls, self.result, self.error = [], result or {"evidence": []}, error
        self.usage = usage

    def __call__(self, question, query_date, usage_log=None):
        self.calls.append((question, query_date))
        if usage_log is not None and self.usage:
            usage_log.append(self.usage)
        if self.error:
            raise self.error
        return self.result


class FakeSynth:
    """A fake synthesise() that remembers the bundle it was given."""
    def __init__(self, error=None, usage=None):
        self.bundles, self.error, self.usage = [], error, usage

    def __call__(self, bundle, usage_log=None):
        self.bundles.append(dict(bundle))
        if usage_log is not None and self.usage:
            usage_log.append(self.usage)
        if self.error:
            raise self.error
        return {"answer": "fake", "declined": False, "cited": [], "sources": [], "events": []}


class FakeCheck:
    """A fake LLM review: returns the given verdicts in turn, then passes."""
    def __init__(self, *reviews, usage=None, error=None):
        self.reviews, self.calls, self.usage, self.error = list(reviews), 0, usage, error

    def __call__(self, state, usage_log=None):
        self.calls += 1
        if usage_log is not None and self.usage:
            usage_log.append(self.usage)
        if self.error:
            raise self.error
        return self.reviews.pop(0) if self.reviews else {"weak": False, "problems": []}


RECORD = {"route": "policy", "check_premise": False, "answerable": True, "reason": "r"}
PRICE = {"town": "TAMPINES", "flat_type": "4 ROOM", "median_price": 620000,
         "n_deals": 299, "note": None}
SETTINGS = {"max_retries": 1, "llm_check": True}


def graph(record=RECORD, policy=None, price=None, synth=None, check=None,
          settings=SETTINGS, **kwargs):
    """Build the graph with a fake router, agents, synthesis and review."""
    return build_graph(fake_route(record, **kwargs), price_fn=price or Spy(PRICE),
                       policy_fn=policy or Spy(), synth_fn=synth or FakeSynth(),
                       check_fn=check or FakeCheck(), self_check_settings=settings)


def steps_named(state, name):
    return [s for s in state["steps"] if s["step"] == name]


# ---------- supervisor ----------

def test_supervisor_receives_question_and_date():
    route = fake_route(RECORD)
    run("Can I use CPF?", today="2026-10-25", app=build_graph(route, price_fn=Spy(), policy_fn=Spy(), synth_fn=FakeSynth(), check_fn=FakeCheck(), self_check_settings=SETTINGS))
    assert route.calls == [("Can I use CPF?", "2026-10-25")]


def test_state_holds_routing_record_and_events():
    events = [{"code": "invalid_combo", "attempt": 1, "detail": "x"}]
    state = run("q", today="2026-10-25", app=graph(events=events))
    assert state["routing"] == RECORD
    assert state["routing_events"] == events


def test_step_log_and_usage():
    usage = {"step": "router", "input_tokens": 10, "output_tokens": 5}
    state = run("q", today="2026-10-25", app=graph(usage=usage))
    assert state["steps"][0]["step"] == "router"
    assert state["steps"][0]["output"] == RECORD
    assert state["usage"] == [usage]


def test_p2_safety_checks_run_inside_the_node():
    """Real safe_route with only the model call faked: route none with a
    premise to check is fixed to policy, and the fix is logged."""
    from functools import partial
    from agents.supervisor.checks import safe_route

    raw = {"route": "none", "check_premise": True, "answerable": False, "reason": "r"}
    route_fn = partial(safe_route, router=lambda question, **kwargs: dict(raw))
    state = run("q", today="2026-10-28", app=build_graph(route_fn, price_fn=Spy(), policy_fn=Spy(), synth_fn=FakeSynth(), check_fn=FakeCheck(), self_check_settings=SETTINGS))
    assert state["routing"]["route"] == "policy"
    assert state["routing"]["check_premise"] is True
    assert [e["code"] for e in state["routing_events"]] == ["invalid_combo"]


def test_routing_errors_propagate():
    def broken(question, **kwargs):
        raise ValueError("No model set")
    with pytest.raises(ValueError):
        run("q", today="2026-10-25", app=build_graph(broken, price_fn=Spy(), policy_fn=Spy(), synth_fn=FakeSynth(), check_fn=FakeCheck(), self_check_settings=SETTINGS))


# ---------- routing condition ----------

@pytest.mark.parametrize("route, expected", [
    ("price", ["price_agent"]),
    ("policy", ["policy_agent"]),
    ("both", ["policy_agent", "price_agent"]),
    ("none", []),
])
def test_route_picks_next_nodes(route, expected):
    state = run("q", today="2026-10-28", app=graph({**RECORD, "route": route}))
    names = [s["step"] for s in state["steps"]]
    assert names[0] == "router" and names[-2:] == ["synthesis", "self_check"]
    assert sorted(names[1:-2]) == expected


# ---------- policy agent ----------

@pytest.mark.parametrize("route, called", [
    ("price", False), ("policy", True), ("both", True), ("none", False),
])
def test_policy_agent_runs_only_when_routed(route, called):
    policy = Spy()
    state = run("q", today="2026-10-28", app=graph({**RECORD, "route": route}, policy))
    assert bool(policy.calls) is called
    assert (state["policy_result"] is not None) is called


def test_policy_agent_receives_question_and_date():
    policy = Spy()
    run("Can I use CPF?", today="2026-10-28", app=graph(policy=policy))
    assert policy.calls == [("Can I use CPF?", "2026-10-28")]


def test_policy_result_and_step():
    result = {"evidence": [{"chunk_id": "H09_D_c0017"}], "decision": "ANSWER_READY"}
    state = run("q", today="2026-10-28", app=graph(policy=Spy(result)))
    assert state["policy_result"] == result
    assert state["agent_errors"] == {}
    step = state["steps"][1]
    assert step["step"] == "policy_agent" and step["stub"] is False


def test_policy_error_is_recorded_not_raised():
    state = run("q", today="2026-10-28", app=graph(policy=Spy(error=ValueError("boom"))))
    assert state["policy_result"] is None
    assert state["agent_errors"] == {"policy": "ValueError: boom"}
    assert state["steps"][1]["error"] == "ValueError: boom"


def test_p2_policy_adapter_in_stub_mode():
    """P2's real adapter, switched to stub mode: no vector store or API needed."""
    stub = get_policy_agent({"policy": "stub", "policy_top_k": 3})
    state = run("q", today="2026-10-28", app=graph(policy=stub))
    assert state["policy_result"]["evidence"][0]["chunk_id"] == "STUB_c0001"
    assert state["steps"][1]["stub"] is True


# ---------- price agent ----------

@pytest.mark.parametrize("route, called", [
    ("price", True), ("policy", False), ("both", True), ("none", False),
])
def test_price_agent_runs_only_when_routed(route, called):
    price = Spy(PRICE)
    state = run("q", today="2026-10-28", app=graph({**RECORD, "route": route}, price=price))
    assert bool(price.calls) is called
    assert (state["price_result"] is not None) is called


def test_price_agent_receives_question_and_date():
    price = Spy(PRICE)
    run("4-room in Tampines?", today="2026-10-28",
        app=graph({**RECORD, "route": "price"}, price=price))
    assert price.calls == [("4-room in Tampines?", "2026-10-28")]


def test_price_result_step_and_usage():
    usage = {"step": "price_filters", "input_tokens": 20, "output_tokens": 8}
    state = run("q", today="2026-10-28",
                app=graph({**RECORD, "route": "price"}, price=Spy(PRICE, usage=usage)))
    assert state["price_result"] == PRICE
    assert state["steps"][1] == {"step": "price_agent", "seconds": state["steps"][1]["seconds"],
                                 "stub": False}
    assert usage in state["usage"]


def test_no_deals_is_a_result_not_an_error():
    empty = {**PRICE, "median_price": None, "n_deals": 0, "note": "No resale deals match."}
    state = run("q", today="2026-10-28",
                app=graph({**RECORD, "route": "price"}, price=Spy(empty)))
    assert state["price_result"]["n_deals"] == 0
    assert state["agent_errors"] == {}


def test_price_error_is_recorded_not_raised():
    state = run("q", today="2026-10-28",
                app=graph({**RECORD, "route": "price"}, price=Spy(error=ValueError("boom"))))
    assert state["price_result"] is None
    assert state["agent_errors"] == {"price": "ValueError: boom"}


def test_both_agents_fail_in_parallel_and_both_errors_are_kept():
    state = run("q", today="2026-10-28", app=graph(
        {**RECORD, "route": "both"},
        price=Spy(error=ValueError("price down")), policy=Spy(error=ValueError("policy down"))))
    assert state["agent_errors"] == {"price": "ValueError: price down",
                                     "policy": "ValueError: policy down"}


def test_both_agents_results_and_usage_are_kept():
    p_usage = {"step": "price_filters", "input_tokens": 1, "output_tokens": 1}
    state = run("q", today="2026-10-28", app=graph(
        {**RECORD, "route": "both"}, price=Spy(PRICE, usage=p_usage),
        policy=Spy({"evidence": [{"chunk_id": "c1"}]})))
    assert state["price_result"] == PRICE
    assert state["policy_result"] == {"evidence": [{"chunk_id": "c1"}]}
    assert p_usage in state["usage"]


# ---------- synthesis ----------

@pytest.mark.parametrize("route", ["price", "policy", "both", "none"])
def test_synthesis_runs_once_for_every_route(route):
    synth = FakeSynth()
    state = run("q", today="2026-10-28", app=graph({**RECORD, "route": route}, synth=synth))
    assert len(synth.bundles) == 1
    assert state["answer"]["answer"] == "fake"


def test_synthesis_receives_both_agents_results():
    synth = FakeSynth()
    run("q", today="2026-10-28", app=graph(
        {**RECORD, "route": "both"}, price=Spy(PRICE),
        policy=Spy({"evidence": [{"chunk_id": "c1"}]}), synth=synth))
    bundle = synth.bundles[0]
    assert bundle["question"] == "q" and bundle["today"] == "2026-10-28"
    assert bundle["routing"]["route"] == "both"
    assert bundle["price_result"] == PRICE
    assert bundle["policy_result"] == {"evidence": [{"chunk_id": "c1"}]}
    assert bundle["agent_errors"] == {}


def test_synthesis_is_told_which_agents_failed():
    synth = FakeSynth()
    run("q", today="2026-10-28", app=graph(
        {**RECORD, "route": "price"}, price=Spy(error=ValueError("boom")), synth=synth))
    assert synth.bundles[0]["agent_errors"] == {"price": "ValueError: boom"}
    assert synth.bundles[0]["price_result"] is None


def test_synthesis_usage_is_logged():
    s_usage = {"step": "synthesis", "input_tokens": 900, "output_tokens": 120}
    state = run("q", today="2026-10-28", app=graph(synth=FakeSynth(usage=s_usage)))
    assert state["usage"][-1] == s_usage
    assert steps_named(state, "synthesis")[-1]["events"] == []


def test_synthesis_error_gives_fallback_answer():
    from agents.supervisor.synthesis import FALLBACK_ANSWER
    state = run("q", today="2026-10-28", app=graph(synth=FakeSynth(error=RuntimeError("down"))))
    assert state["answer"]["answer"] == FALLBACK_ANSWER
    assert state["answer"]["declined"] is True
    assert steps_named(state, "synthesis")[-1]["error"] == "RuntimeError: down"


def test_p2_citation_check_runs_inside_the_node():
    """Real synthesise() with only the model call faked: a citation to a
    passage that does not exist is removed, and sources are built by code."""
    import json
    from functools import partial
    from types import SimpleNamespace
    from agents.supervisor.synthesis import synthesise

    reply = {"answer": "Yes [1].", "cited": [1, 7], "declined": False}
    message = SimpleNamespace(content=json.dumps(reply), refusal=None)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)],
                               usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3))
    client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **kwargs: response)))
    evidence = {"evidence": [{"title": "Mode of Financing", "url": "https://hdb.gov.sg/x",
                              "effective_date": None, "text": "CPF OA can be used."}]}

    state = run("q", today="2026-10-28", app=graph(
        policy=Spy(evidence), synth=partial(synthesise, client=client)))
    assert state["answer"]["cited"] == [1]
    assert state["answer"]["sources"] == [{"n": 1, "title": "Mode of Financing",
                                           "url": "https://hdb.gov.sg/x", "effective_date": None}]
    assert state["answer"]["events"]
    assert state["usage"][-1]["step"] == "synthesis"


# ---------- self check loop ----------

WEAK = {"weak": True, "problems": [
    {"rule": "A1", "issue": "Did not correct the claim.", "target": "synthesis"}]}
EVIDENCE = {"evidence": [{"chunk_id": "c1", "title": "T", "url": "u", "text": "x"}]}


class Flaky(Spy):
    """Fails on the first call, then succeeds."""
    def __call__(self, question, query_date, usage_log=None):
        if not self.calls:
            self.calls.append((question, query_date))
            raise ValueError("timeout")
        return super().__call__(question, query_date, usage_log)


def test_good_answer_is_not_sent_back():
    synth, check = FakeSynth(), FakeCheck()
    state = run("q", today="2026-10-28", app=graph(synth=synth, check=check))
    assert len(synth.bundles) == 1 and check.calls == 1
    assert state["self_check"] == {"verdict": "pass", "problems": [], "retry": []}
    assert state["attempts"] == 0


def test_weak_answer_goes_back_to_synthesis_once_with_feedback():
    synth = FakeSynth()
    state = run("Can singles buy?", today="2026-10-28",
                app=graph(synth=synth, check=FakeCheck(WEAK)))
    assert len(synth.bundles) == 2
    # P2's synthesise() takes no feedback yet, so it rides along in the question.
    assert synth.bundles[0]["question"] == "Can singles buy?"
    assert "Did not correct the claim." in synth.bundles[1]["question"]
    assert state["attempts"] == 1
    assert state["self_check"]["verdict"] == "pass"
    assert [s["step"] for s in state["steps"]][-4:] == [
        "synthesis", "self_check", "synthesis", "self_check"]
    assert "feedback" in steps_named(state, "synthesis")[1]


def test_feedback_is_passed_directly_when_synthesis_accepts_it():
    received = []
    def synth(bundle, usage_log=None, feedback=None):
        received.append((bundle["question"], feedback))
        return {"answer": "a", "declined": False, "cited": [], "sources": [], "events": []}
    run("q", today="2026-10-28", app=graph(synth=synth, check=FakeCheck(WEAK)))
    assert received[0] == ("q", None)
    assert received[1][0] == "q" and "Did not correct the claim." in received[1][1]


def test_still_weak_after_one_retry_stops():
    synth = FakeSynth()
    state = run("q", today="2026-10-28", app=graph(synth=synth, check=FakeCheck(WEAK, WEAK, WEAK)))
    assert len(synth.bundles) == 2
    assert state["self_check"]["verdict"] == "weak"
    assert state["self_check"]["retry"] == []


def test_max_retries_zero_never_sends_back():
    synth = FakeSynth()
    state = run("q", today="2026-10-28", app=graph(
        synth=synth, check=FakeCheck(WEAK), settings={"max_retries": 0, "llm_check": True}))
    assert len(synth.bundles) == 1
    assert state["self_check"]["verdict"] == "weak" and state["self_check"]["retry"] == []


def test_failed_agent_is_retried_and_its_error_cleared():
    price, synth = Flaky(PRICE), FakeSynth()
    state = run("q", today="2026-10-28",
                app=graph({**RECORD, "route": "price"}, price=price, synth=synth))
    assert len(price.calls) == 2
    assert synth.bundles[0]["agent_errors"] == {"price": "ValueError: timeout"}
    assert synth.bundles[1]["agent_errors"] == {}
    assert state["price_result"] == PRICE and state["agent_errors"] == {}
    assert steps_named(state, "self_check")[0]["retry"] == ["price_agent"]


def test_only_the_failed_agent_is_retried():
    price, policy = Spy(PRICE), Flaky(EVIDENCE)
    run("q", today="2026-10-28", app=graph({**RECORD, "route": "both"}, price=price, policy=policy))
    assert len(price.calls) == 1 and len(policy.calls) == 2


def test_supervisor_problem_is_recorded_not_retried():
    review = {"weak": True, "problems": [
        {"rule": "A3", "issue": "Needed resale prices.", "target": "supervisor"}]}
    synth = FakeSynth()
    state = run("q", today="2026-10-28", app=graph(synth=synth, check=FakeCheck(review)))
    assert len(synth.bundles) == 1
    assert state["self_check"]["verdict"] == "weak"
    assert state["self_check"]["retry"] == []


def test_code_check_catches_uncited_answer_without_calling_llm():
    check, synth = FakeCheck(), FakeSynth()   # FakeSynth cites nothing
    state = run("q", today="2026-10-28", app=graph(policy=Spy(EVIDENCE), synth=synth, check=check))
    first = steps_named(state, "self_check")[0]
    assert first["retry"] == ["synthesis"] and first["problems"][0]["rule"] == "A2"
    assert len(synth.bundles) == 2
    assert check.calls == 0   # the code check found it; no model call needed


def test_llm_check_can_be_switched_off():
    check = FakeCheck(WEAK)
    state = run("q", today="2026-10-28", app=graph(
        check=check, settings={"max_retries": 1, "llm_check": False}))
    assert check.calls == 0 and state["self_check"]["verdict"] == "pass"


def test_failed_review_does_not_block_the_answer():
    state = run("q", today="2026-10-28", app=graph(check=FakeCheck(error=RuntimeError("down"))))
    assert state["self_check"]["verdict"] == "pass"
    assert steps_named(state, "self_check")[0]["error"] == "RuntimeError: down"
    assert state["answer"]["answer"] == "fake"


def test_review_usage_is_logged():
    c_usage = {"step": "self_check", "input_tokens": 1500, "output_tokens": 40}
    state = run("q", today="2026-10-28", app=graph(check=FakeCheck(usage=c_usage)))
    assert state["usage"][-1] == c_usage


def test_real_llm_check_with_faked_model_reply():
    """The real llm_check(): builds its review from P2's synthesis context,
    parses the structured reply and logs usage. Only the model call is faked."""
    import json
    from types import SimpleNamespace
    from agents.graph.self_check import llm_check

    sent = []
    message = SimpleNamespace(content=json.dumps(WEAK), refusal=None)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)],
                               usage=SimpleNamespace(prompt_tokens=9, completion_tokens=4))
    def create(**kwargs):
        sent.append(kwargs)
        return response
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    state = {"question": "Can singles buy?", "today": "2026-10-28", "routing": RECORD,
             "price_result": None, "policy_result": EVIDENCE, "agent_errors": {},
             "answer": {"answer": "No.", "cited": [1]}}
    usage = []
    assert llm_check(state, usage_log=usage, client=client) == WEAK
    review = sent[0]["messages"][1]["content"]
    assert "Question: Can singles buy?" in review and "Draft answer:\nNo." in review
    assert "2026-10-28" in sent[0]["messages"][0]["content"]
    assert usage == [{"step": "self_check", "input_tokens": 9, "output_tokens": 4}]
