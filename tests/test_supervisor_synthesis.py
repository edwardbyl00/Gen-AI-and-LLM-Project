"""Tests for agents/supervisor/synthesis.py, using a fake OpenAI client."""

import json
from types import SimpleNamespace

import pytest

from agents.supervisor.adapters import policy_stub, price_stub
from agents.supervisor.pipeline import handle_question
from agents.supervisor.synthesis import (FALLBACK_ANSWER, SynthesisReplyError,
                                         build_context, check_citations,
                                         format_answer, synthesise)


def passage(n, url=True):
    return {"title": f"Rule {n}", "source": "HDB", "text": f"Text of rule {n}.",
            "url": f"https://www.hdb.gov.sg/rule{n}" if url else None,
            "effective_date": "2025-04-01" if n == 1 else None}


def bundle(route="both", false_belief=False, answerable=True, passages=2, price=True):
    return {"question": "q?", "today": "2026-10-22",
            "routing": {"route": route, "false_belief": false_belief,
                        "answerable": answerable, "reason": "r"},
            "price_result": price_stub("q", "2026-10-22") if price else None,
            "policy_result": {"evidence": [passage(i + 1) for i in range(passages)]},
            "agent_errors": {}}


class FakeClient:
    def __init__(self, reply=None, content="unset"):
        text = json.dumps(reply) if content == "unset" else content
        self.message = SimpleNamespace(content=text, refusal="no" if content is None else None)
        self.chat = SimpleNamespace(completions=self)
        self.request = None

    def create(self, **request):
        self.request = request
        return SimpleNamespace(choices=[SimpleNamespace(message=self.message)])


def test_context_numbers_passages_and_flags():
    text, passages = build_context(bundle(false_belief=True))
    assert "[1] Rule 1" in text and "[2] Rule 2" in text
    assert "effective date: 2025-04-01" in text
    assert "possible false belief: yes" in text and "suspicion" in text
    assert "[STUB DATA" in text
    assert len(passages) == 2


def test_context_says_when_sources_are_missing():
    text, _ = build_context(bundle(route="none", passages=0, price=False))
    assert text.count("none provided") == 2


def test_invalid_citations_are_dropped_and_logged():
    valid, events = check_citations([1, 5, 1, 0], [passage(1), passage(2)])
    assert valid == [1]
    assert [e["code"] for e in events] == ["invalid_citation", "invalid_citation"]


def test_sources_are_built_by_code_not_the_model():
    client = FakeClient({"answer": "Yes you can [1].", "cited": [1, 9], "declined": False})
    result = synthesise(bundle(), client=client)
    assert result["sources"] == [{"n": 1, "title": "Rule 1",
                                  "url": "https://www.hdb.gov.sg/rule1",
                                  "effective_date": "2025-04-01"}]
    assert result["events"][0]["code"] == "invalid_citation"
    assert "2026-10-22" in client.request["messages"][0]["content"]


def test_refusal_raises_a_clear_error():
    with pytest.raises(SynthesisReplyError):
        synthesise(bundle(), client=FakeClient(content=None))


def test_format_answer_lists_sources_with_dates():
    text = format_answer({"answer": "A [1].", "sources": [
        {"n": 1, "title": "Rule 1", "url": "https://x", "effective_date": "2025-04-01"},
        {"n": 2, "title": "Rule 2", "url": None, "effective_date": None}]})
    assert "[1] Rule 1, effective 2025-04-01: https://x" in text
    assert "[2] Rule 2: link unavailable" in text


def test_pipeline_uses_fallback_when_synthesis_fails():
    route = lambda q, **kwargs: ({"route": "none", "false_belief": False,
                                    "answerable": False, "reason": "r"}, [])
    def broken(bundle):
        raise RuntimeError("down")
    b = handle_question("q", today="2026-10-22", route_fn=route, synth_fn=broken)
    assert b["answer"]["answer"] == FALLBACK_ANSWER
    assert "RuntimeError" in b["steps"][-1]["error"]
