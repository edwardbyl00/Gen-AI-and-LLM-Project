"""Compute the correct answer for every P1 price test question.

Reads the hand-labelled filters in evaluation/price_questions_P1.csv and
calculates the true figures straight from the cleaned price table.

This deliberately does NOT reuse the price agent's code, so the agent is
never marking its own homework. Re-run it whenever the price data is updated.

Run from the project root:
    python -m evaluation.build_price_ground_truth
"""

from pathlib import Path

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = PROJECT_ROOT / "evaluation" / "price_questions_P1.csv"
OUTPUT = PROJECT_ROOT / "evaluation" / "price_ground_truth_P1.csv"


def true_figures(table, town, flat_type, start, end):
    """Plain filter-and-count on the full table."""
    rows = table[(table["month"] >= start) & (table["month"] <= end)]
    if town != "ALL":
        rows = rows[rows["town"] == town]
    if flat_type != "ALL":
        rows = rows[rows["flat_type"] == flat_type]
    prices = rows["resale_price"]
    if prices.empty:
        return {"true_median": None, "true_mean": None, "true_min": None,
                "true_max": None, "true_count": 0}
    return {
        "true_median": round(prices.median()),
        "true_mean": round(prices.mean()),
        "true_min": int(prices.min()),
        "true_max": int(prices.max()),
        "true_count": int(len(prices)),
    }


def main():
    with open(PROJECT_ROOT / "config.yaml") as f:
        cleaned = yaml.safe_load(f)["price_agent"]["cleaned_data"]
    table = pd.read_csv(PROJECT_ROOT / cleaned, dtype={"month": str, "block": str})
    questions = pd.read_csv(QUESTIONS, dtype=str)

    figures = [true_figures(table, q.exp_town, q.exp_flat_type,
                            q.exp_period_start, q.exp_period_end)
               for q in questions.itertuples()]
    out = pd.concat([questions, pd.DataFrame(figures)], axis=1)
    out.to_csv(OUTPUT, index=False)
    print(out[["question_id", "asks", "true_median", "true_mean", "true_min",
               "true_max", "true_count"]].to_string(index=False))
    print(f"\nSaved: {OUTPUT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
