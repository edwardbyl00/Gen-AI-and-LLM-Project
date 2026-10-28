"""Tests for agents/supervisor/router.py using a fake OpenAI client."""

import json
from types import SimpleNamespace

import pytest

from agents.supervisor.router import RouterReplyError, route_question


def fake_client(content, refusal=None):
    message = SimpleNamespace(content=content, refusal=refusal)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    completions = SimpleNamespace(create=lambda **request: response)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def test_reply_is_turned_into_a_dict():
    reply = {"route": "price", "check_premise": False, "answerable": True, "reason": "x"}
    assert route_question("q", client=fake_client(json.dumps(reply)), today="2026-10-18") == reply


def test_refusal_raises_a_clear_error():
    with pytest.raises(RouterReplyError):
        route_question("q", client=fake_client(None, refusal="I can't help"), today="2026-10-18")
