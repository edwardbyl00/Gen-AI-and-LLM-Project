"""Score the router on a labelled question set.

Usage (makes one API call per question):
    python -m agents.supervisor.evaluate data/labels/practice_routing.csv

Prints a summary and every miss, and saves a results file in
evaluation/results/ so each prompt version's score is kept.
"""

import csv
import sys
import time
from collections import Counter
from datetime import datetime

from agents.supervisor import router
from agents.supervisor.checks import safe_route

FIELDS = ("route", "false_belief", "answerable")
ROUTES = ("price", "policy", "both", "none")
RESULTS_DIR = router.PROJECT_ROOT / "evaluation" / "results"


def to_bool(text):
    """Turn 'true'/'false' from the CSV into True/False."""
    value = str(text).strip().lower()
    if value in ("true", "1", "yes"):
        return True
    if value in ("false", "0", "no"):
        return False
    raise ValueError(f"Not a true/false value: {text!r}")


def load_labels(path):
    """Read the labelled questions from a CSV file."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["false_belief"] = to_bool(row["false_belief"])
        row["answerable"] = to_bool(row["answerable"])
    return rows


def run(rows, route_fn=safe_route):
    """Route every question. Returns one prediction dict per row."""
    predictions = []
    for row in rows:
        start = time.perf_counter()
        record, events = route_fn(row["question"])
        predictions.append({**record, "events": events,
                            "seconds": round(time.perf_counter() - start, 2)})
    return predictions


def score(rows, predictions):
    """Compare predictions with labels. Returns a summary dict."""
    pairs = list(zip(rows, predictions))
    myths = [(r, p) for r, p in pairs if r["false_belief"]]
    not_myths = [(r, p) for r, p in pairs if not r["false_belief"]]
    return {
        "n": len(pairs),
        "correct": {f: sum(p[f] == r[f] for r, p in pairs) for f in FIELDS},
        "all_three": sum(all(p[f] == r[f] for f in FIELDS) for r, p in pairs),
        "myths": len(myths),
        "myths_detected": sum(p["false_belief"] for _, p in myths),
        "false_alarms": sum(p["false_belief"] for _, p in not_myths),
        "confusion": Counter((r["route"], p["route"]) for r, p in pairs),
        "events": sum(len(p["events"]) for _, p in pairs),
    }


def misses(rows, predictions):
    """The rows where at least one field is wrong."""
    return [(r, p) for r, p in zip(rows, predictions)
            if any(p[f] != r[f] for f in FIELDS)]


def print_report(summary, missed):
    n = summary["n"]
    pct = lambda k: f"{k}/{n} ({100 * k / n:.0f}%)" if n else "0/0"
    print(f"\nPrompt: {router.PROMPT_FILE.name}   Model: {router.load_settings()['model']}")
    print(f"Route correct:        {pct(summary['correct']['route'])}")
    print(f"False belief correct: {pct(summary['correct']['false_belief'])}")
    print(f"Answerable correct:   {pct(summary['correct']['answerable'])}")
    print(f"All three correct:    {pct(summary['all_three'])}")
    print(f"Myths detected:       {summary['myths_detected']}/{summary['myths']}")
    print(f"False alarms:         {summary['false_alarms']} (flagged as myth, but not one)")
    print(f"Safety check events:  {summary['events']}")

    print("\nRoute confusion (rows = label, columns = router):")
    print("          " + "".join(f"{c:>8}" for c in ROUTES))
    for label in ROUTES:
        counts = "".join(f"{summary['confusion'][(label, c)]:>8}" for c in ROUTES)
        print(f"{label:>8}  {counts}")

    print(f"\nMisses: {len(missed)}")
    for r, p in missed:
        wrong = ", ".join(f"{f}: expected {r[f]}, got {p[f]}" for f in FIELDS if p[f] != r[f])
        print(f"\n[{r['question_id']}] {r['question']}")
        print(f"  {wrong}")
        print(f"  router's reason: {p['reason']}")


def save_results(rows, predictions, labels_path):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out = RESULTS_DIR / f"routing_{router.PROMPT_FILE.stem}_{stamp}.csv"
    columns = ["question_id", "question", "kind"]
    columns += [f"{f}_{side}" for f in FIELDS for side in ("label", "router")]
    columns += ["all_correct", "reason", "events", "seconds"]
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for r, p in zip(rows, predictions):
            line = {"question_id": r["question_id"], "question": r["question"],
                    "kind": r["kind"], "reason": p["reason"],
                    "events": len(p["events"]), "seconds": p["seconds"],
                    "all_correct": all(p[f] == r[f] for f in FIELDS)}
            for fld in FIELDS:
                line[f"{fld}_label"] = r[fld]
                line[f"{fld}_router"] = p[fld]
            writer.writerow(line)
    return out


if __name__ == "__main__":
    labels_path = sys.argv[1] if len(sys.argv) > 1 else "data/labels/practice_routing.csv"
    rows = load_labels(labels_path)
    print(f"Routing {len(rows)} questions from {labels_path} ...")
    predictions = run(rows)
    print_report(score(rows, predictions), misses(rows, predictions))
    print(f"\nSaved: {save_results(rows, predictions, labels_path)}")
