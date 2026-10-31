"""Tests for agents/supervisor/checks.py. No API calls: every router here
is a fake that returns a scripted reply."""

import json

import pytest

from agents.supervisor.checks import SAFE_FALLBACK, safe_route


def good(**changes):
    """A valid record, with optional changes for a test."""
    record = {"route": "policy", "check_premise": False,
              "answerable": True, "reason": "A rules question."}
    record.update(changes)
    return record


def scripted(*replies):
    """A fake router that returns (or raises) each reply in turn."""
    replies = list(replies)
    calls = []

    def fake_router(question, **kwargs):
        calls.append(question)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    fake_router.calls = calls
    return fake_router


def test_valid_record_passes_unchanged():
    record, events = safe_route("q", router=scripted(good()))
    assert record == good()
    assert events == []


def test_none_with_check_premise_becomes_policy():
    record, events = safe_route("q", router=scripted(
        good(route="none", check_premise=True, answerable=False)))
    assert record["route"] == "policy"
    assert [e["code"] for e in events] == ["invalid_combo"]


def test_none_with_answerable_becomes_not_answerable():
    record, events = safe_route("q", router=scripted(
        good(route="none", answerable=True)))
    assert record["route"] == "none"
    assert record["answerable"] is False
    assert [e["code"] for e in events] == ["invalid_combo"]


def test_both_contradictions_fix_the_belief_first():
    # Once the route becomes policy, the second rule no longer applies.
    record, events = safe_route("q", router=scripted(
        good(route="none", check_premise=True, answerable=True)))
    assert record["route"] == "policy"
    assert record["answerable"] is True
    assert len(events) == 1


def test_bad_value_is_retried_once():
    router = scripted(good(route="myth"), good())
    record, events = safe_route("q", router=router)
    assert record == good()
    assert len(router.calls) == 2
    assert [e["code"] for e in events] == ["malformed_output"]


def test_two_bad_replies_give_the_safe_fallback():
    router = scripted({"route": "price"}, "not a dict")
    record, events = safe_route("q", router=router)
    assert record == SAFE_FALLBACK
    assert len(events) == 2


def test_unreadable_json_is_retried():
    router = scripted(json.JSONDecodeError("bad", "{", 0), good())
    record, events = safe_route("q", router=router)
    assert record == good()
    assert events[0]["code"] == "malformed_output"


def test_empty_reason_counts_as_malformed():
    router = scripted(good(reason="  "), good())
    record, events = safe_route("q", router=router)
    assert len(router.calls) == 2


def test_setup_errors_are_not_hidden():
    # A missing model in config.yaml must stop the program, not be retried.
    with pytest.raises(ValueError):
        safe_route("q", router=scripted(ValueError("No model set")))


# ---- which errors are retried, and which stop the program ----

import httpx
import openai

REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def status_error(error_class, code):
    return error_class("simulated", response=httpx.Response(code, request=REQUEST), body=None)


def test_rate_limit_is_retried():
    router = scripted(status_error(openai.RateLimitError, 429), good())
    record, events = safe_route("q", router=router)
    assert record == good()


def test_timeout_is_retried():
    router = scripted(openai.APITimeoutError(request=REQUEST), good())
    record, events = safe_route("q", router=router)
    assert record == good()


def test_wrong_api_key_stops_the_program():
    with pytest.raises(openai.AuthenticationError):
        safe_route("q", router=scripted(status_error(openai.AuthenticationError, 401)))


def test_wrong_model_name_stops_the_program():
    with pytest.raises(openai.NotFoundError):
        safe_route("q", router=scripted(status_error(openai.NotFoundError, 404)))


def test_unsupported_setting_stops_the_program():
    with pytest.raises(openai.BadRequestError):
        safe_route("q", router=scripted(status_error(openai.BadRequestError, 400)))


def test_refusal_is_retried():
    from agents.supervisor.router import RouterReplyError
    router = scripted(RouterReplyError("No content (refusal: ...)"), good())
    record, events = safe_route("q", router=router)
    assert record == good()
    assert "RouterReplyError" in events[0]["detail"]


# ---- needs_clarification ----

def test_needs_clarification_forces_route_none():
    record, events = safe_route("q", router=scripted(good(
        route="both", check_premise=True, answerable=True,
        needs_clarification=True, clarifying_question="Which town did you mean?")))
    assert record["route"] == "none"
    assert record["check_premise"] is False
    assert record["answerable"] is False
    assert record["needs_clarification"] is True
    assert record["clarifying_question"] == "Which town did you mean?"
    assert [e["code"] for e in events] == ["invalid_combo", "invalid_combo", "invalid_combo"]


def test_needs_clarification_true_without_a_question_is_malformed():
    router = scripted(good(needs_clarification=True, clarifying_question=None),
                      good(needs_clarification=False, clarifying_question=None))
    record, events = safe_route("q", router=router)
    assert record["needs_clarification"] is False
    assert len(router.calls) == 2
    assert events[0]["code"] == "malformed_output"


def test_needs_clarification_absent_is_treated_as_false():
    # Older callers/fakes that omit the field entirely must keep working.
    record, events = safe_route("q", router=scripted(good()))
    assert record == good()
    assert events == []
