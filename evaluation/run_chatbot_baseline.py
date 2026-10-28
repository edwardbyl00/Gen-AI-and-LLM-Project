"""Run the plain chatbot baseline on a question file and save a grading sheet.

The sheet has the same columns as P2's score_answers.py, so the chatbot is
graded and scored exactly like the full system (myth acceptance, honesty,
over-refusal).

Works with either question file format:
- labelled routing files (question_id, question, kind, check_premise, premise_false,
  answerable, ...)
- ground_truth_40q.csv (question_id, question, ...); label columns are left blank

Run from the project root:
    python -m evaluation.run_chatbot_baseline data/labels/practice_routing.csv
"""

import csv
import sys
import time
from datetime import datetime
from pathlib import Path

from agents.baselines.plain_chatbot import chatbot_answer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANSWERS_DIR = PROJECT_ROOT / "evaluation" / "answers"
COLUMNS = ["question_id", "question", "kind", "label_check_premise", "label_premise_false",
           "label_answerable",
           "route", "answer", "model_says_declined", "n_cited", "agent_errors",
           "stub_agents", "input_tokens", "output_tokens", "seconds",
           "grade_declined", "grade_myth_accepted"]


def is_true(value):
    return str(value).strip().upper() in ("TRUE", "1", "YES")


def load_questions(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def answer_all(rows, answer_fn=chatbot_answer):
    """Answer every question. Returns one grading-sheet line per row."""
    lines = []
    for row in rows:
        start = time.perf_counter()
        bundle = answer_fn(row["question"])
        result = bundle["answer"]
        usage = bundle.get("usage", [])
        has_labels = "check_premise" in row
        lines.append({
            "question_id": row["question_id"],
            "question": row["question"],
            "kind": row.get("kind", row.get("category", "")),
            "label_check_premise": row.get("check_premise", ""),
            "label_premise_false": row.get("premise_false", ""),
            "label_answerable": row.get("answerable", ""),
            "route": bundle["routing"]["route"],
            "answer": result["answer"],
            "model_says_declined": result["declined"],
            "n_cited": 0,
            "agent_errors": "",
            "stub_agents": "",
            "input_tokens": sum(u["input_tokens"] or 0 for u in usage),
            "output_tokens": sum(u["output_tokens"] or 0 for u in usage),
            "seconds": round(time.perf_counter() - start, 2),
            # Pre-filled guesses for the grader to check, as in P2's sheet.
            "grade_declined": result["declined"],
            "grade_myth_accepted": ("" if is_true(row.get("premise_false")) else "n/a")
                                   if has_labels else "",
        })
    return lines


def save_sheet(lines, out_dir=ANSWERS_DIR):
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"chatbot_baseline_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(lines)
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python -m evaluation.run_chatbot_baseline <questions.csv>")
    rows = load_questions(sys.argv[1])
    print(f"Answering {len(rows)} questions with the plain chatbot (one model call each) ...")
    print(f"Saved grading sheet: {save_sheet(answer_all(rows))}")
