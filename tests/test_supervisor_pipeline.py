"""Tests for the supervisor pipeline and adapters (no API calls)."""

import pytest

from agents.supervisor.adapters import (get_policy_agent, get_price_agent,
                                        policy_stub, price_real)
from agents.supervisor import pipeline
from agents.supervisor.pipeline import handle_question


@pytest.fixture(autouse=True)
def no_real_synthesis(monkeypatch):
    """Every test here uses a fake synthesis step, so no API calls."""
    fake = lambda bundle, **kwargs: {"answer": "fake", "declined": False,
                           "cited": [], "sources": [], "events": []}
    monkeypatch.setattr(pipeline, "synthesise", fake)


def fake_route(route, false_belief=False, answerable=True):
    record = {"route": route, "false_belief": false_belief,
              "answerable": answerable, "reason": "r"}
    return lambda question, **kwargs: (record, [])


class Spy:
    """A fake agent that remembers whether it was called."""
    def __init__(self, result=None, error=None):
        self.calls, self.result, self.error = [], result or {"ok": True}, error

    def __call__(self, question, query_date):
        self.calls.append((question, query_date))
        if self.error:
            raise self.error
        return self.result


@pytest.mark.parametrize("route, price_called, policy_called", [
    ("price", True, False),
    ("policy", False, True),
    ("both", True, True),
    ("none", False, False),
])
def test_route_decides_which_agents_are_called(route, price_called, policy_called):
    price, policy = Spy(), Spy()
    bundle = handle_question("q", today="2026-10-19", route_fn=fake_route(route),
                             price_fn=price, policy_fn=policy)
    assert bool(price.calls) is price_called
    assert bool(policy.calls) is policy_called
    assert bundle["routing"]["route"] == route


def test_agents_receive_the_question_and_date():
    policy = Spy()
    handle_question("Can I use CPF?", today="2026-10-19",
                    route_fn=fake_route("policy"), policy_fn=policy, price_fn=Spy())
    assert policy.calls == [("Can I use CPF?", "2026-10-19")]


def test_agent_error_is_recorded_not_raised():
    bundle = handle_question("q", today="2026-10-19", route_fn=fake_route("both"),
                             price_fn=Spy(error=RuntimeError("down")), policy_fn=Spy())
    assert bundle["price_result"] is None
    assert "RuntimeError" in bundle["agent_errors"]["price"]
    assert bundle["policy_result"] == {"ok": True}


def test_strict_mode_raises_agent_errors():
    with pytest.raises(RuntimeError):
        handle_question("q", today="2026-10-19", route_fn=fake_route("price"),
                        price_fn=Spy(error=RuntimeError("down")),
                        policy_fn=Spy(), strict=True)


def test_step_log_records_router_and_agents():
    bundle = handle_question("q", today="2026-10-19", route_fn=fake_route("both"),
                             price_fn=Spy(), policy_fn=Spy())
    assert [s["step"] for s in bundle["steps"]] == ["router", "price_agent", "policy_agent", "synthesis"]


def test_config_picks_policy_stub_by_default():
    result = get_policy_agent({"policy": "stub", "policy_top_k": 3})("q", "2026-10-19")
    assert result["stub"] is True and "url" in result["evidence"][0]


def test_price_agent_is_always_real():
    # There's no price stub anymore: get_price_agent() always returns
    # price_real, regardless of what's in settings (see test_price_
    # integration.py for the real adapter's actual behaviour).
    assert get_price_agent() is price_real
    assert get_price_agent({"price": "stub"}) is price_real


def test_token_usage_is_collected_per_call():
    from types import SimpleNamespace
    from agents.supervisor.router import record_usage
    log = []
    record_usage(log, "router", SimpleNamespace(usage=SimpleNamespace(prompt_tokens=900, completion_tokens=40)))
    record_usage(None, "router", None)  # no log given: nothing happens
    assert log == [{"step": "router", "input_tokens": 900, "output_tokens": 40}]
    bundle = handle_question("q", today="2026-10-22", route_fn=fake_route("none"))
    assert bundle["usage"] == []  # fakes make no model calls
