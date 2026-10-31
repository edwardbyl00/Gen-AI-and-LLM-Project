"""Offline evaluation separates corpus, retrieval, gate and answer failures."""

import csv
import json

import pytest

from agents.supervisor.diagnostics import (GRADES, diagnose, main, prepare,
                                           presentation_report, references_template, summarise)


def reference(**changes):
    return {"question_id": "Q1", "question": "Which housing rule applies?",
            "ground_truth_verified": True, "expected_route": "policy",
            "coverage_status": "FULL", "relevant_chunk_ids": ["gold"], **changes}


def record(candidates=None, supplied=None, **changes):
    result = {"decision": "ABSTAIN", "reason": "Missing rule", "evidence": supplied or []}
    if candidates is not None:
        result["retrieved_evidence"] = [{"chunk_id": cid, "text": cid} for cid in candidates]
    return {"review_id": "r1", "question_id": "Q1", "question": "Which housing rule applies?",
            "variant": "B_decomposition", "category": "policy", "answer": "I cannot answer.",
            "bundle": {"routing": {"route": "policy"}, "policy_result": result,
                       "answer": {"declined": True}}, **changes}


def test_existing_but_missed_evidence_is_a_retrieval_issue():
    row = diagnose(record(candidates=["other"]), reference(), {"gold", "other"})
    assert row["all_reference_chunks_in_snapshot"] is True
    assert row["reference_candidate_recall"] == 0
    assert row["diagnostic_flags"] == ["no_reference_chunk_retrieved"]
    assert row["correctness"] == row["faithfulness"] == ""


def test_retrieved_gold_removed_by_gate_is_not_a_retrieval_miss():
    row = diagnose(record(candidates=["gold"]), reference(), {"gold"})
    assert row["reference_candidate_recall"] == 1
    assert row["reference_supplied_recall"] == 0
    assert row["diagnostic_flags"] == ["reference_candidates_not_supplied_to_synthesis"]


def test_missing_corpus_reference_is_not_a_retrieval_miss():
    row = diagnose(record(candidates=[]), reference(), {"other"})
    assert row["missing_gold_chunk_ids"] == ["gold"]
    assert row["diagnostic_flags"] == ["reference_chunks_missing_from_snapshot"]


def test_unverified_reference_and_unknown_candidates_remain_unknown():
    row = diagnose(record(), reference(ground_truth_verified=False), {"gold"})
    assert row["routing_correct"] is None
    assert row["coverage_status"] == "UNKNOWN"
    assert row["all_reference_chunks_in_snapshot"] is None
    assert row["reference_candidate_recall"] is None
    assert row["diagnostic_flags"] == []
    old = diagnose(record(), reference(), {"gold"})
    assert old["candidate_capture_complete"] is False
    assert old["reference_candidate_recall"] is None
    assert old["diagnostic_flags"] == []


def test_all_policy_tasks_count_and_price_results_are_retained():
    run = record()
    run["bundle"]["task_results"] = [
        {"task": {"id": "p1", "agent": "policy"}, "result": {
            "decision": "ABSTAIN", "reason": "Missing", "retrieved_evidence": [], "evidence": []}},
        {"task": {"id": "p2", "agent": "policy"}, "result": {
            "decision": "ANSWER_READY", "retrieved_evidence": [{"chunk_id": "gold"}],
            "evidence": [{"chunk_id": "gold", "text": "Verified rule"}]}},
        {"task": {"id": "price", "agent": "price"}, "result": {"median_price": 123}},
    ]
    row = diagnose(run, reference(), {"gold"})
    assert row["reference_candidate_recall"] == row["reference_supplied_recall"] == 1
    assert len(row["policy_outcomes"]) == 2
    assert row["price_results"] == [{"median_price": 123}]


def test_routing_mismatch_and_verified_gap_are_separate_from_hallucination():
    run = record(candidates=[])
    run["bundle"]["routing"]["route"] = "price"
    row = diagnose(run, reference(coverage_status="NOT_COVERED", relevant_chunk_ids=[]), set())
    assert row["diagnostic_flags"] == ["routing_mismatch", "verified_corpus_gap"]
    assert row["faithfulness"] == ""


def setup_report(tmp_path):
    run_dir = tmp_path / "runs"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(json.dumps({"today": "2026-10-31"}))
    (run_dir / "runs.jsonl").write_text(json.dumps(record(candidates=["gold"])) + "\n")
    refs = tmp_path / "refs.json"
    refs.write_text(json.dumps([reference()]))
    out = tmp_path / "review"
    prepare(run_dir, refs, out)
    return run_dir, refs, out


def write_reviews(out, **updates):
    path = out / "review.csv"
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    rows[0].update(updates)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


def test_summary_has_explicit_pending_scores_and_denominators(tmp_path):
    _, _, out = setup_report(tmp_path)
    write_reviews(out, correctness="0.5", faithfulness="NA")
    report = summarise(out / "diagnostics.json", out / "review.csv")
    metrics = report["summary"][0]["metrics"]
    assert metrics["correctness"]["mean"] == 0.5
    assert metrics["correctness"]["scored_runs"] == 1
    assert metrics["faithfulness"]["mean"] is None
    assert metrics["faithfulness"]["not_applicable"] == 1
    assert metrics["completeness"]["pending"] == 1


@pytest.mark.parametrize("value", ["nan", "inf", "-0.1", "1.1"])
def test_invalid_grades_are_rejected(tmp_path, value):
    _, _, out = setup_report(tmp_path)
    write_reviews(out, correctness=value)
    with pytest.raises(ValueError):
        summarise(out / "diagnostics.json", out / "review.csv")


def test_question_mismatch_and_snapshot_mismatch_are_rejected(tmp_path):
    run_dir, refs, _ = setup_report(tmp_path)
    refs.write_text(json.dumps([reference(question="Different question")]))
    with pytest.raises(ValueError, match="different reference"):
        prepare(run_dir, refs, tmp_path / "bad")
    refs.write_text(json.dumps([reference()]))
    chunks = tmp_path / "chunks.jsonl"
    chunks.write_text('{"chunk_id":"gold"}\n')
    (run_dir / "manifest.json").write_text(json.dumps({
        "fingerprints": {"data/processed/chunks.jsonl": "different-hash"}}))
    with pytest.raises(ValueError, match="snapshot differs"):
        prepare(run_dir, refs, tmp_path / "bad", chunks)


def test_reference_template_does_not_claim_verified_gold(tmp_path):
    questions = tmp_path / "questions.csv"
    questions.write_text("question_id,question\nU1,New question?\n")
    output = tmp_path / "references.json"
    references_template(questions, output)
    row = json.loads(output.read_text())[0]
    assert row["ground_truth_verified"] is False
    assert row["coverage_status"] == "UNKNOWN"
    assert row["expected_route"] == "" and row["relevant_chunk_ids"] == []
    with pytest.raises(FileExistsError):
        references_template(questions, output)


def test_failed_runs_remain_in_report_and_cannot_receive_passing_scores(tmp_path):
    run_dir, refs, _ = setup_report(tmp_path)
    failed = record(error="RuntimeError: execution failed", bundle={})
    (run_dir / "runs.jsonl").write_text(json.dumps(failed) + "\n")
    out = tmp_path / "failures"
    report = prepare(run_dir, refs, out)
    assert report["rows"][0]["diagnostic_flags"] == ["execution_error"]
    assert report["rows"][0]["reference_supplied_recall"] is None
    for grade in ("1", "NA"):
        write_reviews(out, correctness=grade)
        with pytest.raises(ValueError, match="Failed executions"):
            summarise(out / "diagnostics.json", out / "review.csv")
    write_reviews(out, **{metric: "0" for metric in GRADES})
    summary = summarise(out / "diagnostics.json", out / "review.csv")["summary"][0]
    assert summary["runs"] == 1
    assert summary["metrics"]["correctness"]["mean"] == 0


def test_review_ids_must_match_saved_runs(tmp_path):
    _, _, out = setup_report(tmp_path)
    write_reviews(out, review_id="different")
    with pytest.raises(ValueError, match="exactly once"):
        summarise(out / "diagnostics.json", out / "review.csv")


def test_interrupted_experiment_cannot_appear_as_complete(tmp_path):
    run_dir, refs, _ = setup_report(tmp_path)
    (run_dir / "manifest.json").write_text(json.dumps({
        "questions": [{"question_id": "Q1"}], "repeats": 1,
        "variants": {"A_baseline": False, "B_decomposition": True}}))
    with pytest.raises(ValueError, match="Incomplete"):
        prepare(run_dir, refs, tmp_path / "partial")


def test_prepare_merges_precomputed_judge_scores_without_calling_a_model(tmp_path):
    run_dir = tmp_path / "runs"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(json.dumps({"today": "2026-10-31"}))
    (run_dir / "runs.jsonl").write_text(
        json.dumps(record(candidates=["gold"])) + "\n"
        + json.dumps(record(review_id="r2", question_id="Q2", question="Unjudged?")) + "\n"
    )
    refs = tmp_path / "refs.json"
    refs.write_text(json.dumps([reference(), reference(question_id="Q2", question="Unjudged?")]))
    judge_scores = tmp_path / "judge_scores.json"
    judge_scores.write_text(json.dumps({
        "max_score": 10,
        "scores": {"r1": {"total_score": 7, "reason": "Mostly grounded"}},
        "skipped": [{"review_id": "r2", "reason": "not_eligible_for_ground_truth_judge"}],
    }))
    out = tmp_path / "review"
    report = prepare(run_dir, refs, out, judge_scores_path=judge_scores)

    judged, unjudged = report["rows"][0], report["rows"][1]
    assert judged["judge_total_score"] == 7
    assert judged["judge_reason"] == "Mostly grounded"
    assert unjudged["judge_total_score"] is None
    assert unjudged["judge_reason"] == ""

    with (out / "review.csv").open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["judge_total_score"] == "7"
    assert rows[0]["judge_reason"] == "Mostly grounded"
    assert rows[1]["judge_total_score"] == ""

    text = (out / "report.md").read_text()
    assert "7/10" in text
    assert "Not judged" in text


def test_prepared_report_has_readable_stage_and_quality_tables(tmp_path):
    _, _, out = setup_report(tmp_path)
    text = (out / "report.md").read_text()
    assert "| Run | Routing | Policy coverage |" in text
    assert "| Run | LLM-judge score | Evidence relevance | Faithfulness | Correctness |" in text
    assert "Not judged" in text
    assert "| Q1 / B\\_decomposition / repeat 1 | Pass: policy (expected: policy) |" in text
    assert "ABSTAIN — Missing rule" in text
    assert "Pending" in text and "Unknown" in text
    assert "No scores (0/1 scored)" in text


def test_presented_scores_include_denominators_and_review_findings(tmp_path):
    _, _, out = setup_report(tmp_path)
    write_reviews(out, correctness="0", faithfulness="NA", completeness="0.5",
                  what_went_well="Clear refusal", what_went_wrong="Missed rule",
                  recommended_fix="Review the evidence gate")
    text = presentation_report(summarise(out / "diagnostics.json", out / "review.csv"))
    assert "0.0% (1/1 scored)" in text
    assert "| Pending | N/A | 0% | 50% | Pending |" in text
    assert "Clear refusal | Missed rule | Review the evidence gate" in text


def test_question_text_cannot_break_tables_or_inject_html():
    row = diagnose(record(candidates=[]), reference(), {"gold"})
    row["question"] = "a | b\n<script>alert(1)</script> [link](url)"
    row["answer"] = "**answer**"
    text = presentation_report({"rows": [row]})
    assert "a \\| b<br>&lt;script&gt;" in text
    assert "<script>" not in text
    assert "\\[link\\](url)" in text
    assert "\\*\\*answer\\*\\*" in text


def test_cli_writes_json_and_presentation_report(tmp_path, monkeypatch):
    _, _, out = setup_report(tmp_path)
    output = tmp_path / "summary.json"
    arguments = ["diagnostics", "summarise", str(out / "diagnostics.json"),
                 str(out / "review.csv"), "--out", str(output)]
    monkeypatch.setattr("sys.argv", arguments)
    main()
    assert json.loads(output.read_text())["summary"]
    assert "# Question evaluation report" in output.with_suffix(".md").read_text()
    output.unlink()
    with pytest.raises(FileExistsError, match="already exists"):
        main()
    assert not output.exists()


def test_category_named_all_does_not_double_summary_counts():
    row = diagnose(record(category="All", candidates=[]), reference(), {"gold"})
    text = presentation_report({"rows": [row]})
    assert "| All | 1 | 1 |" in text
    assert "| Category: All | 1 | 1 |" in text
