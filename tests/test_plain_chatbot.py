"""Tests for the plain chatbot baseline. No API key needed: the LLM is faked."""

import json
from types import SimpleNamespace

from agents.baselines.plain_chatbot import (
    ROUTE_LABEL, chatbot_answer, chatbot_price_estimate,
)
from evaluation.run_chatbot_baseline import COLUMNS, answer_all


class FakeClient:
    def __init__(self, reply):
        self.sent = []
        self.reply = reply
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **request):
        self.sent.append(request)
        message = SimpleNamespace(content=json.dumps(self.reply), refusal=None)
        usage = SimpleNamespace(prompt_tokens=50, completion_tokens=20)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def test_chatbot_answer_has_pipeline_shape():
    client = FakeClient({"answer": "The MOP is 5 years.", "declined": False})
    bundle = chatbot_answer("What is the MOP?", today="2026-10-25", client=client)
    assert bundle["routing"]["route"] == ROUTE_LABEL
    assert bundle["price_result"] is None and bundle["policy_result"] is None
    assert bundle["answer"] == {"answer": "The MOP is 5 years.", "declined": False,
                                "cited": [], "sources": [], "events": []}
    assert bundle["usage"][0]["input_tokens"] == 50


def test_chatbot_gets_no_documents_or_prices():
    client = FakeClient({"answer": "x", "declined": False})
    chatbot_answer("What is the MOP?", today="2026-10-25", client=client)
    messages = client.sent[0]["messages"]
    assert len(messages) == 2                      # system prompt + question only
    assert messages[1]["content"] == "What is the MOP?"
    assert "2026-10-25" in messages[0]["content"]


def test_chatbot_price_estimate_parses_numbers():
    reply = {"median_price": 650000, "mean_price": 660000, "min_price": None,
             "max_price": None, "n_deals": None, "declined": False}
    out = chatbot_price_estimate("4-room Tampines?", today="2026-10-25",
                                 client=FakeClient(reply))
    assert out == reply


def test_grading_sheet_matches_team_columns():
    rows = [
        {"question_id": "PR_P1_03", "question": "q1", "kind": "myth",
         "false_belief": "TRUE", "answerable": "TRUE"},
        {"question_id": "H29", "question": "q2", "category": "price"},  # 40q format
    ]
    fake = lambda q: chatbot_answer(q, today="2026-10-25",
                                    client=FakeClient({"answer": "a", "declined": False}))
    lines = answer_all(rows, answer_fn=fake)
    assert all(set(line) == set(COLUMNS) for line in lines)
    assert lines[0]["grade_myth_accepted"] == ""      # myth: grader must fill in
    assert lines[1]["label_false_belief"] == ""       # no labels in 40q format
    assert lines[1]["kind"] == "price"
