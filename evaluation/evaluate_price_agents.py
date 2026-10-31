"""P1 approach study: approach A vs approach B vs the plain chatbot on price questions.

For each question in evaluation/price/price_ground_truth_P1.csv it records:
- filters_correct  (A and B only): town, flat type AND exact period all match the labels
- figure_correct   : the figure the question asks for is within 1% of the true value
                     (count questions must match exactly)
- no_data_correct  : for questions with no true answer (future, unknown place), the
                     system gave no figure instead of inventing one
- seconds, tokens  : cost of each answer

Run from the project root (needs the API key in .env):
    python -m evaluation.evaluate_price_agents
Results: evaluation/results/price_agents_<time>.csv and a printed summary.
"""

import csv
import time
from datetime import datetime
from pathlib import Path

from agents.baselines.plain_chatbot import chatbot_price_estimate
from agents.price.agent import price_agent
from agents.price.sql_agent import price_agent_sql

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GROUND_TRUTH = PROJECT_ROOT / "evaluation" / "price" / "price_ground_truth_P1.csv"
RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results"
TOLERANCE = 0.01

# Which output field holds the figure each kind of question asks for.
FIGURE_FIELD = {"median": "median_price", "mean": "mean_price", "min": "min_price",
                "max": "max_price", "count": "n_deals"}
TRUE_FIELD = {"median": "true_median", "mean": "true_mean", "min": "true_min",
              "max": "true_max", "count": "true_count"}


def to_number(value):
    if value in (None, "", "nan", "NaN"):
        return None
    return float(value)


def figure_is_correct(asks, given, true):
    """Within 1% of the true value; counts must be exact."""
    if given is None or true is None:
        return False
    if asks == "count":
        return int(given) == int(true)
    return abs(given - true) <= TOLERANCE * true


def score_one(row, system, output, seconds, tokens):
    """One result line for one question and one system."""
    asks = row["asks"]
    line = {"question_id": row["question_id"], "question": row["question"],
            "difficulty": row["difficulty"], "asks": asks, "system": system,
            "seconds": round(seconds, 2), "tokens": tokens, "error": ""}

    if output is None:  # the call itself failed
        line.update({"filters_correct": "", "figure_given": "", "true_figure": "",
                     "figure_correct": False, "no_data_correct": ""})
        return line

    if system == "chatbot":
        line["filters_correct"] = "n/a"
    else:
        line["filters_correct"] = (
            output.get("town") == row["exp_town"]
            and output.get("flat_type") == row["exp_flat_type"]
            and output.get("period_start") == row["exp_period_start"]
            and output.get("period_end") == row["exp_period_end"])

    if asks == "none":
        # No true answer exists: correct only if no figure was given.
        figures = [output.get(f) for f in ("median_price", "mean_price", "min_price",
                                           "max_price")]
        line.update({"figure_given": "", "true_figure": "",
                     "figure_correct": "n/a",
                     "no_data_correct": all(f is None for f in figures)})
        return line

    given = to_number(output.get(FIGURE_FIELD[asks]))
    true = to_number(row[TRUE_FIELD[asks]])
    line.update({"figure_given": given, "true_figure": true,
                 "figure_correct": figure_is_correct(asks, given, true),
                 "no_data_correct": "n/a"})
    return line


def run_system(name, fn, row):
    """Call one system on one question, timing it and counting tokens."""
    usage = []
    start = time.perf_counter()
    try:
        output = fn(row["question"], row["query_date"], usage_log=usage)
        error = ""
    except Exception as exc:  # recorded, so one failure does not stop the run
        output, error = None, f"{type(exc).__name__}: {exc}"
    seconds = time.perf_counter() - start
    tokens = sum((u.get("input_tokens") or 0) + (u.get("output_tokens") or 0) for u in usage)
    line = score_one(row, name, output, seconds, tokens)
    line["error"] = error
    return line


SYSTEMS = {
    "A_filter_tool": lambda q, d, usage_log: price_agent(q, d, usage_log=usage_log),
    "B_text_to_sql": lambda q, d, usage_log: price_agent_sql(q, d, usage_log=usage_log),
    "chatbot": lambda q, d, usage_log: chatbot_price_estimate(q, d, usage_log=usage_log),
}


def evaluate(rows, systems=SYSTEMS):
    return [run_system(name, fn, row) for row in rows for name, fn in systems.items()]


def summarise(lines):
    """Per system: share of filters right, figures right, no-data handled, avg time."""
    summary = {}
    for system in dict.fromkeys(l["system"] for l in lines):
        mine = [l for l in lines if l["system"] == system]
        def share(key):
            scored = [l[key] for l in mine if isinstance(l[key], bool)]
            return (sum(scored), len(scored))
        summary[system] = {
            "filters_correct": share("filters_correct"),
            "figure_correct": share("figure_correct"),
            "no_data_correct": share("no_data_correct"),
            "avg_seconds": round(sum(l["seconds"] for l in mine) / len(mine), 2),
            "avg_tokens": round(sum(l["tokens"] for l in mine) / len(mine)),
            "errors": sum(1 for l in mine if l["error"]),
        }
    return summary


def print_summary(summary):
    def fmt(pair):
        hits, total = pair
        return f"{hits}/{total} = {hits / total:.0%}" if total else "n/a"
    print(f"{'System':16}{'Filters right':18}{'Figure right':18}{'No-data right':18}"
          f"{'Avg secs':10}{'Avg tokens':12}Errors")
    for system, s in summary.items():
        print(f"{system:16}{fmt(s['filters_correct']):18}{fmt(s['figure_correct']):18}"
              f"{fmt(s['no_data_correct']):18}{s['avg_seconds']:<10}{s['avg_tokens']:<12}"
              f"{s['errors']}")


def save(lines):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"price_agents_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(lines[0]))
        writer.writeheader()
        writer.writerows(lines)
    return out


if __name__ == "__main__":
    with open(GROUND_TRUTH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"Running {len(rows)} price questions on {len(SYSTEMS)} systems ...")
    lines = evaluate(rows)
    print(f"Saved: {save(lines).relative_to(PROJECT_ROOT)}\n")
    print_summary(summarise(lines))
