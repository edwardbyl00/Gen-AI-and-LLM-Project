"""Offline stage diagnostics for saved evaluation runs; never calls a model."""

import argparse
import csv
import hashlib
import json
import math
from html import escape
from collections import Counter
from pathlib import Path
from statistics import mean


GRADES = ("evidence_relevance", "faithfulness", "correctness", "completeness",
          "appropriate_abstention")


def _cell(value):
    """Keep question/answer text inside its Markdown table cell."""
    text = escape(str(value), quote=False).replace("\\", "\\\\")
    for character in ("|", "`", "*", "_", "[", "]"):
        text = text.replace(character, "\\" + character)
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def _table(headers, rows):
    lines = ["| " + " | ".join(_cell(h) for h in headers) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(_cell(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def _score(row, metric):
    value = row.get(metric)
    if row.get(metric + "_status") == "not_applicable":
        return "N/A"
    return "Pending" if value is None or value == "" else f"{float(value):.0%}"


def presentation_report(report):
    """Readable tables for presentation, with unknown/pending results explicit."""
    rows = report["rows"]
    sections = ["# Question evaluation report", "Scores are rubric scores on a 0–100% scale. "
        "Pending means not reviewed; Unknown means not established; N/A means not applicable. "
        "Reference recall measures matching labeled chunks, not answer correctness."]
    sections += [_table(["Query date", "Executions", "Unique questions", "Graded executions"], [[
        report.get("query_date") or "Unknown", len(rows), len({r["question_id"] for r in rows}),
        sum(all(r.get(g + "_status") in ("reviewed", "not_applicable") for g in GRADES) for r in rows)]])]

    grouped = {}
    for row in rows:
        for key in ((row["variant"], "All"), (row["variant"], "Category: " + row["category"])):
            grouped.setdefault(key, []).append(row)

    def average(group, metric):
        values = [float(r[metric]) for r in group if r.get(metric) is not None and r.get(metric) != ""]
        return (f"{mean(values):.1%} ({len(values)}/{len(group)} scored)" if values
                else f"No scores (0/{len(group)} scored)")

    sections += ["## Results by variant and category", "Counts in each score show scored executions / "
                 "total executions. Category rows are subsets of All; do not add them together.",
        _table(["Variant", "Category", "Runs", "Questions", "Routing accuracy", "Faithfulness", "Correctness"], [
            [variant, category, len(group), len({r["question_id"] for r in group}),
             average(group, "routing_correct"), average(group, "faithfulness"), average(group, "correctness")]
            for (variant, category), group in sorted(grouped.items())])]

    def label(row):
        return f"{row['question_id']} / {row['variant'] or 'unspecified'} / repeat {row['repeat']}"

    def route(row):
        actual, expected = row["actual_route"], row["expected_route"]
        status = "Unknown" if row["routing_correct"] is None else "Pass" if row["routing_correct"] else "Fail"
        return f"{status}: {actual or 'unknown'} (expected: {expected or 'unverified'})"

    def recall(row, metric):
        return "Unknown" if row[metric] is None else f"{row[metric]:.0%}"

    sections += ["## Stage results by execution",
        _table(["Run", "Routing", "Policy coverage", "Reference chunks in corpus", "Candidate recall",
                "Supplied recall", "Policy decision / reason"], [
            [label(r), route(r), r["coverage_status"],
             "Unknown" if r["all_reference_chunks_in_snapshot"] is None
             else "All present" if r["all_reference_chunks_in_snapshot"] else "Some missing",
             recall(r, "reference_candidate_recall"), recall(r, "reference_supplied_recall"),
             "\n".join(f"{o['task_id']}: {o.get('decision') or 'unknown'} — {o.get('reason') or 'no reason recorded'}"
                       for o in r["policy_outcomes"]) or "Not run / not recorded"] for r in rows])]
    sections += ["## Answer quality by execution", _table([
        "Run", "Evidence relevance", "Faithfulness", "Correctness", "Completeness", "Appropriate abstention"
    ], [[label(r), *(_score(r, grade) for grade in GRADES)] for r in rows])]

    flag_counts = Counter(flag for r in rows for flag in r["diagnostic_flags"])
    sections += ["## Diagnostic observations", "Flags are investigation leads, not confirmed causes. "
                 "A verified corpus gap can lead to an appropriate abstention.",
        _table(["Observation", "Executions flagged", "Total executions"], [
            [flag.replace("_", " "), count, len(rows)] for flag, count in sorted(flag_counts.items())]
            or [["No automatic flags recorded; review may still be pending", 0, len(rows)]])]
    sections += ["## What went well and what needs fixing", _table([
        "Run", "Observations / errors", "What went well", "What went wrong", "Recommended fix", "Reviewer notes"
    ], [[label(r), "\n".join([*(f.replace("_", " ") for f in r["diagnostic_flags"]),
                             *([r["execution_error"]] if r["execution_error"] else [])]) or "No automatic flags",
         *(r.get("review", {}).get(key) or "Pending review" for key in
           ("what_went_well", "what_went_wrong", "recommended_fix", "reviewer_notes"))] for r in rows])]
    sections += ["## Questions and answers", _table(["Run", "Question", "Answer"], [
        [label(r), r["question"], r["answer"] or "No answer recorded"] for r in rows])]
    return "\n\n".join(sections) + "\n"


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ids(value):
    if isinstance(value, list):
        return {str(item).strip() for item in value if str(item).strip()}
    return {item.strip() for item in (value or "").split(";") if item.strip()}


def references_template(questions_path, output_path):
    """Keep reviewer references separate from the question-only inference input."""
    rows = read_csv(questions_path)
    seen, references = set(), []
    for row in rows:
        qid, question = row.get("question_id", "").strip(), row.get("question", "").strip()
        if not qid or not question or qid in seen:
            raise ValueError("Questions need unique nonempty IDs and nonempty text")
        seen.add(qid)
        references.append({"question_id": qid, "question": question,
            "ground_truth_verified": False, "expected_route": "",
            "coverage_status": "UNKNOWN", "relevant_chunk_ids": [],
            "reference_answer": "", "required_conditions": "",
            "reference_urls": [], "reference_as_of": "", "review_notes": ""})
    if not references:
        raise ValueError("Question list is empty")
    with Path(output_path).open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(references, indent=2, ensure_ascii=False) + "\n")


def load_references(path):
    rows = json.loads(Path(path).read_text()) if Path(path).suffix == ".json" else read_csv(path)
    result = {}
    for row in rows:
        qid = row.get("question_id", "").strip()
        if not qid or qid in result or not row.get("question", "").strip():
            raise ValueError("References need unique nonempty IDs and question text")
        if row.get("expected_route", "") not in ("", "price", "policy", "both", "none"):
            raise ValueError(f"Invalid expected_route: {qid}")
        if row.get("coverage_status", "UNKNOWN") not in ("UNKNOWN", "FULL", "PARTIAL", "NOT_COVERED", "NOT_APPLICABLE"):
            raise ValueError(f"Invalid coverage_status: {qid}")
        result[qid] = row
    return result


def policy_results(bundle):
    if "task_results" in bundle:
        return [(r["task"]["id"], r.get("result")) for r in bundle["task_results"]
                if r["task"]["agent"] == "policy"]
    return [("policy", bundle.get("policy_result"))]


def diagnose(record, reference, corpus_ids):
    bundle = record.get("bundle") or {}
    verified = str(reference.get("ground_truth_verified", False)).lower() == "true"
    gold = ids(reference.get("relevant_chunk_ids")) if verified else set()
    actual_route = bundle.get("routing", {}).get("route", "")
    expected_route = reference.get("expected_route", "") if verified else ""
    available, candidates, candidate_ids, supplied_ids, decisions = [], [], set(), set(), []
    observed_candidates = False
    for task_id, result in policy_results(bundle):
        if result is None:
            continue
        decisions.append({"task_id": task_id, "decision": result.get("decision"),
                          "reason": result.get("reason"), "trace": result.get("trace", [])})
        # Support both adapter-shaped and direct policy-agent saved results.
        retrieval = result.get("retrieval", result)
        evidence = retrieval.get("evidence", [])
        available.extend({**item, "task_id": task_id} for item in evidence)
        supplied_ids.update(item["chunk_id"] for item in evidence if item.get("chunk_id"))
        if "retrieved_evidence" in retrieval:
            observed_candidates = True
            raw = retrieval["retrieved_evidence"]
            candidates.extend({**item, "task_id": task_id} for item in raw)
            candidate_ids.update(item["chunk_id"] for item in raw if item.get("chunk_id"))
        else:
            # Older traces prove supplied passages were retrieved, but cannot
            # establish which other candidates the assessor rejected.
            candidate_ids.update(item["chunk_id"] for item in evidence if item.get("chunk_id"))
    known_candidates = all(
        "retrieved_evidence" in (result.get("retrieval", result))
        for _, result in policy_results(bundle) if result is not None
    ) and observed_candidates
    coverage = reference.get("coverage_status", "UNKNOWN") if verified else "UNKNOWN"
    missing = sorted(gold - corpus_ids) if corpus_ids is not None else None
    failures = []
    errors = [record.get("error"), *bundle.get("agent_errors", {}).values(),
              *(step.get("error") for step in bundle.get("steps", []))]
    execution_error = "; ".join(dict.fromkeys(str(error) for error in errors if error))
    if execution_error:
        failures.append("execution_error")
    if expected_route and actual_route and actual_route != expected_route:
        failures.append("routing_mismatch")
    if missing:
        failures.append("reference_chunks_missing_from_snapshot")
    if coverage == "NOT_COVERED":
        failures.append("verified_corpus_gap")
    policy_searched = actual_route in ("policy", "both")
    # Require complete candidate observations and matching corpus references
    # before labeling absence as a retrieval miss.
    if gold and missing == [] and policy_searched and known_candidates and not execution_error:
        if not gold & candidate_ids:
            failures.append("no_reference_chunk_retrieved")
        elif not gold & supplied_ids:
            failures.append("reference_candidates_not_supplied_to_synthesis")
    price_results = [r.get("result") for r in bundle.get("task_results", [])
                     if r["task"]["agent"] == "price"] if "task_results" in bundle else [bundle.get("price_result")]
    return {"review_id": record["review_id"], "question_id": record["question_id"],
        "question": record["question"], "variant": record.get("variant", ""),
        "repeat": record.get("repeat", 1), "pipeline": record.get("pipeline", ""),
        "category": record.get("category", "unspecified"),
        "answer": record.get("answer", ""), "actual_route": actual_route,
        "routing_reason": bundle.get("routing", {}).get("reason", ""),
        "expected_route": expected_route,
        "routing_correct": actual_route == expected_route if expected_route and actual_route else None,
        "reference_verified": verified, "coverage_status": coverage,
        "reference": reference, "gold_chunk_ids": sorted(gold),
        "missing_gold_chunk_ids": missing,
        "all_reference_chunks_in_snapshot": not missing if gold and missing is not None else None,
        "candidate_capture_complete": known_candidates,
        "candidate_chunk_ids": sorted(candidate_ids), "supplied_chunk_ids": sorted(supplied_ids),
        "reference_candidate_recall": len(gold & candidate_ids) / len(gold)
            if gold and known_candidates and not execution_error else None,
        "reference_supplied_recall": len(gold & supplied_ids) / len(gold)
            if gold and bundle and not execution_error else None,
        "policy_outcomes": decisions, "policy_candidates": candidates,
        "supplied_policy_evidence": available, "price_results": price_results,
        "answer_declined": (bundle.get("answer") or {}).get("declined"),
        "diagnostic_flags": failures, "execution_error": str(execution_error) if execution_error else "",
        **{grade: "" for grade in GRADES}}


def prepare(run_dir, references_path, out_dir, chunks_path=None):
    run_dir, out_dir = Path(run_dir), Path(out_dir)
    refs = load_references(references_path)
    records = [json.loads(line) for line in (run_dir / "runs.jsonl").read_text().splitlines() if line.strip()]
    if not records or len({r["review_id"] for r in records}) != len(records):
        raise ValueError("Saved runs must be nonempty with unique review IDs")
    corpus_ids = None
    manifest = json.loads((run_dir / "manifest.json").read_text())
    if all(key in manifest for key in ("questions", "repeats", "variants")):
        expected = {(q["question_id"], repeat, variant) for q in manifest["questions"]
                    for repeat in range(1, manifest["repeats"] + 1) for variant in manifest["variants"]}
        actual = {(r["question_id"], r.get("repeat"), r.get("variant")) for r in records}
        if actual != expected or len(records) != len(expected):
            raise ValueError("Incomplete or duplicated experiment schedule")
    if any(record.get("config_changed") for record in records):
        raise ValueError("Configuration changed during inference; experiment is not comparable")
    if chunks_path is not None:
        original = manifest.get("fingerprints", {}).get("data/processed/chunks.jsonl")
        if original and original != digest(chunks_path):
            raise ValueError("Chunk snapshot differs from the inference manifest")
        corpus_ids = {json.loads(line)["chunk_id"] for line in Path(chunks_path).read_text().splitlines() if line.strip()}
    rows = []
    for record in records:
        ref = refs.get(record["question_id"])
        if ref is None or " ".join(ref["question"].split()) != " ".join(record["question"].split()):
            raise ValueError(f"Missing or different reference question: {record['question_id']}")
        rows.append(diagnose(record, ref, corpus_ids))
    out_dir.mkdir(parents=True, exist_ok=False)
    report = {"run_directory": str(run_dir.resolve()), "references_sha256": digest(references_path),
              "chunks_sha256": digest(chunks_path) if chunks_path else None,
              "manifest_sha256": digest(run_dir / "manifest.json"), "runs_sha256": digest(run_dir / "runs.jsonl"),
              "query_date": manifest.get("today"), "rows": rows}
    (out_dir / "diagnostics.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    (out_dir / "report.md").write_text(presentation_report(report), encoding="utf-8")
    columns = ["review_id", "question_id", "question", "answer", *GRADES,
               "what_went_well", "what_went_wrong", "recommended_fix", "reviewer_notes"]
    with (out_dir / "review.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            values = {key: row.get(key, "") for key in columns}
            writer.writerow({key: "'" + value if isinstance(value, str) and value.lstrip().startswith(
                ("=", "+", "-", "@")) else value for key, value in values.items()})
    return report


def summarise(report_path, review_path):
    report = json.loads(Path(report_path).read_text())
    reviews = read_csv(review_path)
    by_id = {row["review_id"]: row for row in reviews}
    if len(by_id) != len(reviews) or set(by_id) != {r["review_id"] for r in report["rows"]}:
        raise ValueError("Review rows must match every saved run exactly once")
    groups = {}
    for row in report["rows"]:
        review = by_id[row["review_id"]]
        for metric in GRADES:
            value = review.get(metric, "").strip()
            if value in ("", "NA"):
                if value == "NA" and row["execution_error"]:
                    raise ValueError("Failed executions must have zero quality scores, not NA")
                row[metric] = None
                row[metric + "_status"] = "pending" if not value else "not_applicable"
            else:
                number = float(value)
                if not math.isfinite(number) or not 0 <= number <= 1:
                    raise ValueError(f"Invalid {metric}: {row['review_id']}")
                if row["execution_error"] and number != 0:
                    raise ValueError("Failed executions must have zero quality scores")
                row[metric] = number
                row[metric + "_status"] = "reviewed"
        row["review"] = review
        for key in ((row["variant"], "all"), (row["variant"], "category:" + row["category"])):
            groups.setdefault(key, []).append(row)
    summaries = []
    for (variant, group), rows in sorted(groups.items()):
        metrics = {}
        for metric in ("routing_correct", "reference_candidate_recall", "reference_supplied_recall", *GRADES):
            known = [r[metric] for r in rows if r[metric] is not None]
            metrics[metric] = {"mean": mean(known) if known else None, "scored_runs": len(known),
                               "total_runs": len(rows)}
            if metric in GRADES:
                metrics[metric].update(Counter(r[metric + "_status"] for r in rows))
        summaries.append({"variant": variant, "group": group, "runs": len(rows),
            "unique_questions": len({r["question_id"] for r in rows}), "metrics": metrics,
            "diagnostic_flags": dict(Counter(flag for r in rows for flag in r["diagnostic_flags"]))})
    return {**report, "summary": summaries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    template = commands.add_parser("template")
    template.add_argument("questions", type=Path)
    template.add_argument("--out", type=Path, required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("run_dir", type=Path)
    prep.add_argument("--references", type=Path, required=True)
    prep.add_argument("--chunks", type=Path)
    prep.add_argument("--out", type=Path, required=True)
    summary = commands.add_parser("summarise")
    summary.add_argument("report", type=Path)
    summary.add_argument("review", type=Path)
    summary.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "template":
        references_template(args.questions, args.out)
    elif args.command == "prepare":
        prepare(args.run_dir, args.references, args.out, args.chunks)
    else:
        result = summarise(args.report, args.review)
        markdown_path = args.out.with_suffix(".md")
        if markdown_path == args.out:
            raise ValueError("Use a JSON output path; the Markdown report is written alongside it")
        if args.out.exists() or markdown_path.exists():
            raise FileExistsError("Output report already exists; choose a fresh output name")
        presentation = presentation_report(result)
        with args.out.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        with markdown_path.open("x", encoding="utf-8") as stream:
            stream.write(presentation)


if __name__ == "__main__":
    main()
