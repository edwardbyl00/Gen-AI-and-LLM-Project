"""Tests for agents/supervisor/score_answers.py (no API calls)."""

import pytest

from agents.supervisor.score_answers import answer_all, score_sheet


def line(qid, myth, answerable, declined, accepted):
    return {"question_id": qid, "label_false_belief": str(myth),
            "label_answerable": str(answerable),
            "grade_declined": str(declined), "grade_myth_accepted": accepted}


def test_three_rates():
    lines = [
        line("m1", True, True, False, "true"),     # myth accepted
        line("m2", True, True, False, "false"),    # myth corrected
        line("u1", False, False, True, "n/a"),     # correctly declined
        line("u2", False, False, False, "n/a"),    # should have declined
        line("a1", False, True, True, "n/a"),      # wrongly declined
        line("a2", False, True, False, "n/a"),
    ]
    s = score_sheet(lines)
    assert s["myth_acceptance"] == {"hits": 1, "total": 2, "rate": 0.5}
    assert s["honesty"] == {"hits": 1, "total": 2, "rate": 0.5}
    assert (s["over_refusal"]["hits"], s["over_refusal"]["total"]) == (1, 4)


def test_ungraded_sheet_cannot_be_scored():
    with pytest.raises(ValueError, match="m1"):
        score_sheet([line("m1", True, True, False, "")])


def test_answer_all_builds_a_prefilled_sheet():
    rows = [{"question_id": "q1", "question": "Q?", "kind": "myth",
             "false_belief": True, "answerable": True}]
    fake = lambda q: {
        "routing": {"route": "both"},
        "answer": {"answer": "A [1].", "declined": False, "cited": [1],
                   "sources": [{"n": 1, "title": "T", "url": "u", "effective_date": None}]},
        "agent_errors": {}, "steps": [{"step": "price_agent", "stub": True}],
        "usage": [{"step": "router", "input_tokens": 900, "output_tokens": 40},
                  {"step": "synthesis", "input_tokens": 1500, "output_tokens": 200}],
    }
    [sheet] = answer_all(rows, answer_fn=fake)
    assert sheet["grade_myth_accepted"] == ""       # myth: left blank for the grader
    assert sheet["grade_declined"] is False          # pre-filled, to be checked
    assert (sheet["input_tokens"], sheet["output_tokens"]) == (2400, 240)
    assert sheet["stub_agents"] == "price_agent"
    assert "Sources:" in sheet["answer"]
