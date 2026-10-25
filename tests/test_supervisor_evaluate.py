"""Tests for the scoring logic in agents/supervisor/evaluate.py (no API calls)."""

import pytest

from agents.supervisor.evaluate import load_labels, misses, run, score, to_bool


def row(qid, route, fb, ans, premise_false=None):
    return {"question_id": qid, "question": qid, "route": route,
            "check_premise": fb, "answerable": ans,
            "premise_false": fb if premise_false is None else premise_false}


def test_to_bool():
    assert to_bool("TRUE") is True and to_bool(" false ") is False
    with pytest.raises(ValueError):
        to_bool("maybe")


def test_score_counts_each_field_separately():
    rows = [row("a", "price", False, True), row("b", "both", True, True)]
    preds = [dict(row("a", "price", False, True), events=[]),
             dict(row("b", "policy", True, True), events=[{"code": "x"}])]
    s = score(rows, preds)
    assert s["correct"] == {"route": 1, "check_premise": 2, "answerable": 2}
    assert s["all_three"] == 1
    assert (s["premises"], s["premises_detected"], s["false_alarms"]) == (1, 1, 0)
    assert (s["myths"], s["myths_detected"]) == (1, 1)
    assert s["confusion"][("both", "policy")] == 1
    assert s["events"] == 1
    assert [r["question_id"] for r, _ in misses(rows, preds)] == ["b"]


def test_false_alarm_is_counted():
    rows = [row("a", "policy", False, True)]
    preds = [dict(row("a", "policy", True, True), events=[])]
    assert score(rows, preds)["false_alarms"] == 1


def test_run_uses_the_given_router():
    fake = lambda q: ({"route": "none", "check_premise": False,
                       "answerable": False, "reason": "r"}, [])
    preds = run([row("a", "none", False, False)], route_fn=fake)
    assert preds[0]["route"] == "none" and "seconds" in preds[0]


def test_practice_file_is_valid():
    rows = load_labels("data/labels/practice_routing.csv")
    assert rows
    assert all(r["question_id"].strip() and r["question"].strip() for r in rows)
    assert len({r["question_id"] for r in rows}) == len(rows)
    assert all(r["route"] in ("price", "policy", "both", "none") for r in rows)
    # R3: a flagged belief never goes with route none
    assert not any(r["check_premise"] and r["route"] == "none" for r in rows)


def test_true_premise_counts_as_premise_but_not_myth():
    # "Since the MOP is 5 years..." assumes a claim (to check) that is true.
    rows = [row("t", "policy", True, True, premise_false=False)]
    preds = [dict(row("t", "policy", True, True), events=[])]
    s = score(rows, preds)
    assert (s["premises"], s["premises_detected"]) == (1, 1)
    assert s["myths"] == 0
