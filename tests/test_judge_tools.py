"""The judge pre-pass only grades eligible rows and never skips silently."""

import json

from agents.supervisor import judge_tools
from agents.supervisor.diagnostics import diagnose


def reference(**changes):
    return {"question_id": "Q1", "question": "Which housing rule applies?",
            "ground_truth_verified": True, "expected_route": "policy",
            "coverage_status": "FULL", "relevant_chunk_ids": ["gold"],
            "supporting_evidence": "Verified rule text", **changes}


def record(decision="ANSWER_READY", route="policy", declined=False, **changes):
    result = {"decision": decision, "reason": "Resolved",
              "evidence": [{"chunk_id": "gold", "text": "Verified rule"}]}
    return {"review_id": "r1", "question_id": "Q1", "question": "Which housing rule applies?",
            "variant": "B_decomposition", "category": "policy", "answer": "You qualify.",
            "bundle": {"routing": {"route": route}, "policy_result": result,
                       "answer": {"declined": declined}}, **changes}


def test_verified_policy_row_is_eligible():
    row = diagnose(record(), reference(), None)
    assert judge_tools.eligible(row) is True


def test_unverified_reference_is_not_eligible():
    row = diagnose(record(), reference(ground_truth_verified=False), None)
    assert judge_tools.eligible(row) is False


def test_price_and_mixed_routes_are_not_eligible():
    assert judge_tools.eligible(diagnose(record(route="price"), reference(), None)) is False
    assert judge_tools.eligible(diagnose(record(route="both"), reference(), None)) is False


def test_execution_error_is_not_eligible():
    row = diagnose(record(error="boom"), reference(), None)
    assert judge_tools.eligible(row) is False


def test_run_prepass_judges_eligible_rows_and_records_skips(tmp_path, monkeypatch):
    run_dir = tmp_path / "runs"
    run_dir.mkdir()
    (run_dir / "runs.jsonl").write_text(
        json.dumps(record()) + "\n"
        + json.dumps(record(review_id="r2", question_id="Q2", question="Price only",
                             route="price")) + "\n"
    )
    refs = tmp_path / "refs.json"
    refs.write_text(json.dumps([
        reference(),
        reference(question_id="Q2", question="Price only", expected_route="price"),
    ]))

    captured = {}

    def fake_judge_against_ground_truth(**kwargs):
        captured.update(kwargs)
        return {"judgement": {"total_score": 8, "reason": "Well grounded"}}

    monkeypatch.setattr(judge_tools, "judge_against_ground_truth", fake_judge_against_ground_truth)
    monkeypatch.setattr(judge_tools, "max_score", lambda: 10)

    out = tmp_path / "judge_scores.json"
    judge_tools.run_prepass(run_dir, refs, out)

    payload = json.loads(out.read_text())
    assert payload["max_score"] == 10
    assert payload["scores"] == {"r1": {"total_score": 8, "reason": "Well grounded"}}
    assert payload["skipped"] == [
        {"review_id": "r2", "reason": "not_eligible_for_ground_truth_judge"}
    ]
    assert captured["coverage_status"] == "FULL"
    assert captured["supporting_evidence"] == "Verified rule text"
