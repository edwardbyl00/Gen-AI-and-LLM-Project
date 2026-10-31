"""Score every answer in a saved ablation run with the faithfulness-style
LLM judge (src/llm_judge.py), with no ground-truth reference required.

Unlike `agents.supervisor.judge_tools prepass`, this judges every execution
that has an answer and policy evidence, regardless of route, coverage or
whether a reference has been verified. It is not a replacement for the
ground-truth-gated prepass or for independent human grading (see
Docs/stage_evaluation.md and Docs/llm_judge_validation.md) -- treat its
output as a fast first read to compare against human grades separately,
not as the scored result.

Usage (needs the API key in .env; makes one real judge call per execution):
    python -m scripts.judge_ablation_answers evaluation/ablation/new_questions_v1
"""

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from llm_judge import MODEL, judge_answer, max_score  # noqa: E402


def load_records(run_dir):
    path = Path(run_dir) / "runs.jsonl"
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def judge_record(record):
    bundle = record.get("bundle") or {}
    answer = bundle.get("answer") or {}
    policy_result = bundle.get("policy_result") or {}

    if record.get("error") or not answer.get("answer"):
        return None, "execution_error_or_no_answer"

    result = judge_answer(
        question=bundle.get("question", record.get("question")),
        answer=answer["answer"],
        evidence=policy_result.get("evidence") or [],
    )
    return result, None


def run(run_dir, out_path):
    records = load_records(run_dir)
    scores, errors = {}, []

    for record in records:
        review_id = record["review_id"]
        print(f"Judging {review_id} ({record['question_id']}, {record['variant']})...")
        started = time.perf_counter()
        try:
            result, skip_reason = judge_record(record)
        except Exception as error:  # noqa: BLE001 -- one bad row must not stop the batch
            errors.append({"review_id": review_id, "reason": f"{type(error).__name__}: {error}"})
            continue
        if skip_reason:
            errors.append({"review_id": review_id, "reason": skip_reason})
            continue
        entry = dict(result["judgement"])
        entry["usage"] = result["usage"]
        entry["latency_seconds"] = round(time.perf_counter() - started, 3)
        entry["question_id"] = record["question_id"]
        entry["variant"] = record["variant"]
        entry["category"] = record.get("category")
        scores[review_id] = entry

    out = {"model": MODEL, "max_score": max_score(), "scores": scores, "errors": errors}
    Path(out_path).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Judged {len(scores)}/{len(records)} executions ({len(errors)} skipped). Wrote {out_path}")
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="Saved ablation run directory (has runs.jsonl)")
    parser.add_argument("--out", type=Path, default=None,
                        help="Default: <run_dir>_llm_judge_scores.json next to run_dir")
    args = parser.parse_args()

    out_path = args.out or args.run_dir.parent / f"{args.run_dir.name}_llm_judge_scores.json"
    run(args.run_dir, out_path)


if __name__ == "__main__":
    main()
