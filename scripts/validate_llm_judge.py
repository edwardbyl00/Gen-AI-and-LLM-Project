"""
Validate the LLM-as-judge used in scripts/evaluate_agentic_answers.py.

Two checks, run separately so the (paid) swap-check never blocks the
(free) human-check:

1. swap-check
   Order-sensitivity probe. A pointwise judge has no "answer A vs
   answer B" position to swap, so the equivalent bias here is evidence
   order: re-run the ground-truth judge on the same (question, answer)
   pair with the retrieved evidence list reversed, and flag any pair
   whose total_score moves by more than --threshold points. A judge
   that is actually reading the evidence for content, not position,
   should be stable under this reversal.

2. human-check
   Agreement with a human grader. `emit-template` writes a CSV with
   one row per (question, system) already scored by the judge, with
   blank human_<field> columns for a reviewer to fill in. `score`
   reads the filled-in CSV back and reports exact-match rate and mean
   absolute error per rubric field against the judge's own scores.

Usage:
    python scripts/validate_llm_judge.py swap-check --n 5
    python scripts/validate_llm_judge.py human-check emit-template \
        --out evaluation/agentic/human_label_sample.csv
    python scripts/validate_llm_judge.py human-check score \
        --labels evaluation/agentic/human_label_sample.csv
"""

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ground_truth_judge import (  # noqa: E402
    GROUND_TRUTH_RUBRIC,
    judge_against_ground_truth,
)

RESULTS_PATH = (
    PROJECT_ROOT
    / "evaluation"
    / "agentic"
    / "agentic_vs_baseline_pilot_10q_judged.json"
)

GROUND_TRUTH_PATH = (
    PROJECT_ROOT
    / "evaluation"
    / "retrieval"
    / "ground_truth_40q.csv"
)

RUBRIC_FIELDS = list(GROUND_TRUTH_RUBRIC.keys())


def load_results():
    if not RESULTS_PATH.exists():
        raise SystemExit(
            f"No results file at {RESULTS_PATH}. "
            "Run scripts/evaluate_agentic_answers.py --judge first."
        )

    with RESULTS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def load_ground_truth_rows():
    with GROUND_TRUTH_PATH.open(
        encoding="utf-8-sig",
        newline="",
    ) as f:
        return {
            row["question_id"]: row
            for row in csv.DictReader(f)
        }


def iter_system_results(results):
    """Yield (question_id, system_name, row, system_result) for each
    scored (question, system) pair in a results file."""

    for row in results:
        for system_name in ("baseline", "agentic"):
            system_result = row.get(system_name)

            if system_result is None:
                continue

            yield row["question_id"], system_name, row, system_result


# ---------------------------------------------------------------- #
# 1. swap-check: evidence-order sensitivity
# ---------------------------------------------------------------- #

def run_swap_check(n, threshold):
    results = load_results()
    gt_rows = load_ground_truth_rows()

    pairs = list(iter_system_results(results))[:n] if n else list(
        iter_system_results(results)
    )

    report = []

    for question_id, system_name, row, system_result in pairs:
        gt_row = gt_rows[question_id]
        evidence = system_result["evidence"]

        forward = judge_against_ground_truth(
            question=row["question"],
            answer=system_result["answer"]["answer"],
            decision=system_result["decision"],
            declined=system_result["answer"]["declined"],
            evidence=evidence,
            coverage_status=gt_row["coverage_status"],
            supporting_evidence=gt_row["supporting_evidence"],
            required_conditions=gt_row["required_conditions"],
            review_notes=gt_row.get("review_notes", ""),
        )["judgement"]

        reversed_evidence = list(reversed(evidence))

        backward = judge_against_ground_truth(
            question=row["question"],
            answer=system_result["answer"]["answer"],
            decision=system_result["decision"],
            declined=system_result["answer"]["declined"],
            evidence=reversed_evidence,
            coverage_status=gt_row["coverage_status"],
            supporting_evidence=gt_row["supporting_evidence"],
            required_conditions=gt_row["required_conditions"],
            review_notes=gt_row.get("review_notes", ""),
        )["judgement"]

        delta_total = abs(
            forward["total_score"] - backward["total_score"]
        )

        field_deltas = {
            field: abs(forward[field] - backward[field])
            for field in RUBRIC_FIELDS
        }

        unstable = delta_total >= threshold or any(
            d >= threshold for d in field_deltas.values()
        )

        report.append(
            {
                "question_id": question_id,
                "system": system_name,
                "forward_total": forward["total_score"],
                "backward_total": backward["total_score"],
                "delta_total": delta_total,
                "field_deltas": field_deltas,
                "unstable": unstable,
            }
        )

        flag = "UNSTABLE" if unstable else "stable"

        print(
            f"[{flag}] {question_id} ({system_name}): "
            f"forward={forward['total_score']} "
            f"backward={backward['total_score']} "
            f"delta={delta_total}"
        )

    unstable_count = sum(1 for r in report if r["unstable"])

    print(
        f"\n{unstable_count}/{len(report)} "
        f"(question, system) pairs unstable at threshold={threshold}"
    )

    out_path = (
        PROJECT_ROOT
        / "evaluation"
        / "agentic"
        / "judge_swap_check.json"
    )

    out_path.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print(f"Wrote {out_path}")


# ---------------------------------------------------------------- #
# 2. human-check: agreement with a human grader
# ---------------------------------------------------------------- #

def emit_template(out_path):
    results = load_results()

    fieldnames = (
        ["question_id", "system", "question"]
        + [f"judge_{f}" for f in RUBRIC_FIELDS]
        + ["judge_total"]
        + [f"human_{f}" for f in RUBRIC_FIELDS]
        + ["human_total", "human_notes"]
    )

    rows = []

    for question_id, system_name, row, system_result in iter_system_results(
        results
    ):
        judgement = system_result.get(
            "ground_truth_judge", {}
        ).get("judgement")

        if judgement is None:
            continue

        out_row = {
            "question_id": question_id,
            "system": system_name,
            "question": row["question"],
            "judge_total": judgement["total_score"],
        }

        for field in RUBRIC_FIELDS:
            out_row[f"judge_{field}"] = judgement[field]
            out_row[f"human_{field}"] = ""

        out_row["human_total"] = ""
        out_row["human_notes"] = ""

        rows.append(out_row)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(
        f"Wrote {len(rows)} rows to {out_path}\n"
        f"Fill in the human_* columns (0/1/2 per field), "
        f"then run:\n"
        f"  python scripts/validate_llm_judge.py human-check score "
        f"--labels {out_path}"
    )


def score_against_human(labels_path):
    labels_path = Path(labels_path)

    with labels_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    graded = [
        row
        for row in rows
        if all(
            row.get(f"human_{field}", "").strip() != ""
            for field in RUBRIC_FIELDS
        )
    ]

    if not graded:
        raise SystemExit(
            f"No fully-graded rows found in {labels_path}. "
            "Fill in all human_<field> columns for at least one row."
        )

    print(
        f"{len(graded)}/{len(rows)} rows have complete human labels.\n"
    )

    per_field = {}

    for field in RUBRIC_FIELDS:
        judge_vals = [int(r[f"judge_{field}"]) for r in graded]
        human_vals = [int(r[f"human_{field}"]) for r in graded]

        exact_match = sum(
            1
            for j, h in zip(judge_vals, human_vals)
            if j == h
        ) / len(graded)

        mae = statistics.mean(
            abs(j - h) for j, h in zip(judge_vals, human_vals)
        )

        per_field[field] = {
            "exact_match_rate": round(exact_match, 3),
            "mean_abs_error": round(mae, 3),
        }

        print(
            f"{field:28s} "
            f"exact_match={exact_match:.0%}  "
            f"MAE={mae:.2f}"
        )

    disagreements = [
        row
        for row in graded
        if row["judge_total"] != row["human_total"]
        and row["human_total"].strip() != ""
    ]

    print(
        f"\n{len(disagreements)}/{len(graded)} rows disagree on "
        f"total_score (judge vs human)."
    )

    for row in sorted(
        disagreements,
        key=lambda r: abs(
            int(r["judge_total"]) - int(r["human_total"] or 0)
        ),
        reverse=True,
    )[:5]:
        print(
            f"  {row['question_id']} ({row['system']}): "
            f"judge_total={row['judge_total']} "
            f"human_total={row['human_total']} "
            f"-- {row.get('human_notes', '')}"
        )

    out_path = labels_path.with_suffix(".summary.json")

    out_path.write_text(
        json.dumps(
            {
                "n_graded": len(graded),
                "n_total": len(rows),
                "per_field": per_field,
                "n_total_score_disagreements": len(disagreements),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\nWrote {out_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    swap = sub.add_parser(
        "swap-check",
        help="Re-judge with evidence order reversed; flag instability.",
    )
    swap.add_argument(
        "--n",
        type=int,
        default=5,
        help="Number of (question, system) pairs to check (default 5).",
    )
    swap.add_argument(
        "--threshold",
        type=int,
        default=1,
        help="Score-point delta that counts as unstable (default 1).",
    )

    human = sub.add_parser(
        "human-check",
        help="Compare judge scores against a human-labeled sample.",
    )
    human_sub = human.add_subparsers(
        dest="human_command", required=True
    )

    emit = human_sub.add_parser(
        "emit-template",
        help="Write a CSV of judge scores with blank human_* columns.",
    )
    emit.add_argument(
        "--out",
        default=str(
            PROJECT_ROOT
            / "evaluation"
            / "agentic"
            / "human_label_sample.csv"
        ),
    )

    score = human_sub.add_parser(
        "score",
        help="Score a filled-in human-label CSV against the judge.",
    )
    score.add_argument("--labels", required=True)

    args = parser.parse_args()

    if args.command == "swap-check":
        run_swap_check(args.n, args.threshold)
    elif args.command == "human-check":
        if args.human_command == "emit-template":
            emit_template(args.out)
        elif args.human_command == "score":
            score_against_human(args.labels)


if __name__ == "__main__":
    main()
