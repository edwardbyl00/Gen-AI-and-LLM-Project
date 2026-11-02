"""Tests for the LangGraph pipeline (no API calls)."""

import pytest

import agents.supervisor.tasks as task_module
from agents.graph.graph import build_graph, run
from agents.supervisor.adapters import get_policy_agent


@pytest.fixture(autouse=True)
def baseline_config(tmp_path, monkeypatch):
    """These tests cover the graph without decomposition, so they read a config with
    decompose: false whatever the project default is (decomposition has its own tests
    in test_graph_decomposition.py). Same approach as that file."""
    config = tmp_path / "config.yaml"
    config.write_text("supervisor:\n  decompose: false\n")
    monkeypatch.setattr(task_module, "CONFIG_FILE", config)


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
    return build_graph(fake_route(record, **kwargs), decompose=False, price_fn=price or Spy(PRICE),
                       policy_fn=policy or Spy(), synth_fn=synth or FakeSynth(),
                       check_fn=check or FakeCheck(), self_check_settings=settings)


def steps_named(state, name):
    return [s for s in state["steps"] if s["step"] == name]


# ---------- supervisor ----------

def test_supervisor_receives_question_and_date():
    route = fake_route(RECORD)
    run("Can I use CPF?", today="2026-10-25", app=build_graph(route, decompose=False, price_fn=Spy(), policy_fn=Spy(), synth_fn=FakeSynth(), check_fn=FakeCheck(), self_check_settings=SETTINGS))
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
    state = run("q", today="2026-10-28", app=build_graph(route_fn, decompose=False, price_fn=Spy(), policy_fn=Spy(), synth_fn=FakeSynth(), check_fn=FakeCheck(), self_check_settings=SETTINGS))
    assert state["routing"]["route"] == "policy"
    assert state["routing"]["check_premise"] is True
    assert [e["code"] for e in state["routing_events"]] == ["invalid_combo"]


def test_needs_clarification_bypasses_agents_and_model():
    """An unclear question must not call either agent, and synthesis must
    return the clarifying question without a model call."""
    from agents.supervisor.synthesis import synthesise as real_synthesise

    record = {"route": "both", "check_premise": False, "answerable": True,
              "reason": "ambiguous referent", "needs_clarification": True,
              "clarifying_question": "Which town and flat type did you mean?"}
    price, policy = Spy(), Spy()
    state = run("What about it?", today="2026-10-25",
               app=graph(record=record, price=price, policy=policy, synth=real_synthesise))
    assert price.calls == [] and policy.calls == []
    assert state["answer"]["needs_clarification"] is True
    assert state["answer"]["answer"] == "Which town and flat type did you mean?"
    assert state["answer"]["declined"] is True


def test_routing_errors_propagate():
    def broken(question, **kwargs):
        raise ValueError("No model set")
    with pytest.raises(ValueError):
        run("q", today="2026-10-25", app=build_graph(broken, decompose=False, price_fn=Spy(), policy_fn=Spy(), synth_fn=FakeSynth(), check_fn=FakeCheck(), self_check_settings=SETTINGS))


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


def test_policy_usage_is_logged():
    """P2's adapter reports P5's evidence-check tokens through usage_log."""
    p_usage = {"step": "policy_assessor", "input_tokens": 700, "output_tokens": 90, "calls": 1}
    state = run("q", today="2026-10-30", app=graph(policy=Spy(EVIDENCE, usage=p_usage)))
    assert p_usage in state["usage"]


# ---------- chat memory ----------

from langgraph.checkpoint.memory import MemorySaver

USAGE = {"step": "router", "input_tokens": 10, "output_tokens": 2}


class FakeRewrite:
    """A fake follow-up rewrite: looks the message up in `rewrites`, else
    returns it unchanged. Remembers each message and the history it saw."""
    def __init__(self, rewrites=None, error=None, usage=None):
        self.rewrites, self.error, self.usage, self.calls = rewrites or {}, error, usage, []

    def __call__(self, message, history, today, usage_log=None):
        self.calls.append((message, [t["user_question"] for t in history], today))
        if usage_log is not None and self.usage:
            usage_log.append(self.usage)
        if self.error:
            raise self.error
        return self.rewrites.get(message, message)


def chat_graph(record=RECORD, policy=None, price=None, check=None, route=None, rewrite=None,
               **kwargs):
    """The fake graph with a checkpointer, so turns are kept per thread_id."""
    return build_graph(route or fake_route(record, usage=USAGE, **kwargs), decompose=False,
                       price_fn=price or Spy(PRICE), policy_fn=policy or Spy(),
                       synth_fn=FakeSynth(), check_fn=check or FakeCheck(),
                       self_check_settings=SETTINGS, checkpointer=MemorySaver(),
                       rewrite_fn=rewrite or FakeRewrite())


def test_without_checkpointer_there_is_no_history():
    state = run("q", today="2026-11-01", app=graph())
    assert "history" not in state


def test_thread_id_needs_a_checkpointer():
    with pytest.raises(ValueError, match="checkpointer"):
        run("q", today="2026-11-01", app=graph(), thread_id="chat-1")


def test_each_turn_is_added_to_history():
    app = chat_graph()
    run("first", today="2026-11-01", app=app, thread_id="chat-1")
    state = run("second", today="2026-11-01", app=app, thread_id="chat-1")
    assert [t["user_question"] for t in state["history"]] == ["first", "second"]
    assert state["history"][-1]["answer"] == state["answer"]


def test_threads_keep_separate_histories():
    app = chat_graph()
    run("a1", today="2026-11-01", app=app, thread_id="a")
    run("b1", today="2026-11-01", app=app, thread_id="b")
    state = run("a2", today="2026-11-01", app=app, thread_id="a")
    assert [t["user_question"] for t in state["history"]] == ["a1", "a2"]


def test_steps_and_usage_cover_this_turn_only():
    app = chat_graph()
    first = run("first", today="2026-11-01", app=app, thread_id="chat-1")
    second = run("second", today="2026-11-01", app=app, thread_id="chat-1")
    # Only a follow-up (turn 2 on) has a rewrite step; the rest is the same.
    assert [s["step"] for s in second["steps"]] == ["rewrite"] + [s["step"] for s in first["steps"]]
    assert second["usage"] == first["usage"]
    assert second["cost_usd"] == first["cost_usd"]
    # Each saved turn keeps its own step log, not a running total.
    assert second["history"][0]["steps"] == first["steps"]


def test_errors_and_results_do_not_leak_into_the_next_turn():
    price = Spy(error=RuntimeError("down"))
    app = chat_graph(record={**RECORD, "route": "price"}, price=price)
    first = run("price question", today="2026-11-01", app=app, thread_id="chat-1")
    assert first["agent_errors"] == {"price": "RuntimeError: down"}
    price.error = None
    second = run("next question", today="2026-11-01", app=app, thread_id="chat-1")
    assert second["agent_errors"] == {}
    assert second["attempts"] == 0
    assert second["history"][0]["agent_errors"] == first["agent_errors"]


def test_chat_memory_keeps_chats_after_reopening(tmp_path):
    """chat_memory() saves to SQLite, so a chat survives an app restart."""
    from agents.graph.graph import chat_memory

    db = tmp_path / "chat" / "chats.sqlite"
    def app(saver):
        return build_graph(fake_route(RECORD), decompose=False, price_fn=Spy(), policy_fn=Spy(),
                           synth_fn=FakeSynth(), check_fn=FakeCheck(), self_check_settings=SETTINGS,
                           checkpointer=saver, rewrite_fn=FakeRewrite())
    first = chat_memory(db)
    run("first", today="2026-11-01", app=app(first), thread_id="chat-1")
    first.conn.close()
    reopened = chat_memory(db)
    state = run("second", today="2026-11-01", app=app(reopened), thread_id="chat-1")
    reopened.conn.close()
    assert [t["user_question"] for t in state["history"]] == ["first", "second"]


# ---------- follow-up rewrite ----------

def test_first_turn_is_not_rewritten():
    rewrite = FakeRewrite()
    state = run("What did 4-room flats in Tampines sell for?", today="2026-11-01",
                app=chat_graph(rewrite=rewrite), thread_id="chat-1")
    assert rewrite.calls == []
    assert steps_named(state, "rewrite") == []


def test_graph_without_memory_has_no_rewrite_node():
    assert "rewrite" not in graph().get_graph().nodes
    assert "rewrite" in chat_graph().get_graph().nodes


def test_follow_up_is_rewritten_before_routing():
    route = fake_route(RECORD)
    rewrite = FakeRewrite({"what about Bishan?": "What did 4-room flats in Bishan sell for?"})
    app = chat_graph(route=route, rewrite=rewrite)
    run("What did 4-room flats in Tampines sell for?", today="2026-11-01", app=app, thread_id="c")
    state = run("what about Bishan?", today="2026-11-01", app=app, thread_id="c")
    # The rewrite saw the earlier turn; the router got the standalone question.
    assert rewrite.calls == [("what about Bishan?",
                              ["What did 4-room flats in Tampines sell for?"], "2026-11-01")]
    assert route.calls[-1] == ("What did 4-room flats in Bishan sell for?", "2026-11-01")
    turn = state["history"][-1]
    assert turn["user_question"] == "what about Bishan?"
    assert turn["question"] == "What did 4-room flats in Bishan sell for?"
    [step] = steps_named(state, "rewrite")
    assert step["changed"] is True and step["output"] == turn["question"]


def test_rewrite_usage_is_counted():
    r_usage = {"step": "rewrite", "input_tokens": 300, "output_tokens": 20}
    app = chat_graph(rewrite=FakeRewrite(usage=r_usage))
    run("first", today="2026-11-01", app=app, thread_id="c")
    state = run("second", today="2026-11-01", app=app, thread_id="c")
    assert r_usage in state["usage"]
    assert r_usage in state["history"][-1]["usage"]


def test_failed_rewrite_keeps_the_message():
    route = fake_route(RECORD)
    app = chat_graph(route=route, rewrite=FakeRewrite(error=RuntimeError("timeout")))
    run("first", today="2026-11-01", app=app, thread_id="c")
    state = run("what about Bishan?", today="2026-11-01", app=app, thread_id="c")
    assert route.calls[-1][0] == "what about Bishan?"
    [step] = steps_named(state, "rewrite")
    assert step["error"] == "RuntimeError: timeout" and step["changed"] is False


def test_chat_context_shows_earlier_turns_and_price_data():
    from agents.graph.rewrite import MAX_TURNS, chat_context

    turns = [{"user_question": f"q{n}", "question": f"q{n}", "answer": {"answer": f"a{n}"},
              "price_result": None} for n in range(MAX_TURNS + 1)]
    turns[-1].update(user_question="and Bishan?", question="What did 4-room flats in Bishan sell for?",
                     price_result={"town": "BISHAN", "flat_type": "4 ROOM",
                                   "period_start": "2025-10", "period_end": "2026-09"})
    context = chat_context(turns, "and 5-room?")
    assert "q0" not in context  # only the last MAX_TURNS turns
    assert "Understood as: What did 4-room flats in Bishan sell for?" in context
    assert "town BISHAN, flat type 4 ROOM, 2025-10 to 2026-09" in context
    assert context.endswith("New message: and 5-room?")


def test_rewrite_question_sends_the_chat_and_reads_the_reply():
    import json
    from types import SimpleNamespace

    from agents.graph.rewrite import rewrite_question

    sent = []
    message = SimpleNamespace(content=json.dumps({"question": "Bishan 4-room?"}), refusal=None)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)],
                               usage=SimpleNamespace(prompt_tokens=50, completion_tokens=5))
    def create(**kwargs):
        sent.append(kwargs)
        return response
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    history = [{"user_question": "Tampines 4-room?", "question": "Tampines 4-room?",
                "answer": {"answer": "About $620,000."}, "price_result": None}]
    usage = []
    assert rewrite_question("and Bishan?", history, "2026-11-01", usage_log=usage,
                            client=client) == "Bishan 4-room?"
    assert "2026-11-01" in sent[0]["messages"][0]["content"]
    assert "User: Tampines 4-room?" in sent[0]["messages"][1]["content"]
    assert usage == [{"step": "rewrite", "input_tokens": 50, "output_tokens": 5}]
