"""Price table loading, period rules and the price numbers (no LLM here).

Everything in this file is plain code, so the numbers are always exact and
can be checked against the table by hand.
"""

from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = PROJECT_ROOT / "config.yaml"

ALL = "ALL"  # used for town or flat_type when the question names none


def load_price_settings():
    """Read the price_agent section of config.yaml."""
    with open(CONFIG_FILE) as f:
        config = yaml.safe_load(f) or {}
    return config.get("price_agent", {})


@lru_cache(maxsize=2)
def load_price_table(path=None):
    """Load the cleaned price table once and keep it in memory."""
    path = path or load_price_settings()["cleaned_data"]
    return pd.read_csv(PROJECT_ROOT / path, dtype={"block": str, "month": str})


def shift_month(month, n):
    """'2026-09' shifted by -11 -> '2025-10'."""
    return (pd.Period(month, freq="M") + n).strftime("%Y-%m")


def resolve_period(table, start, end, default_months, query_date=None, last_n_months=None):
    """Turn the extracted period into an exact one the data can answer.

    Rules:
    - "Last N months": the latest N complete months of data.
    - No period given, or only vague words like "recently": the latest
      `default_months` complete months of data (routing spec R2).
    - Only a start given: from that start to the latest data.
    - Only an end given: from the first data to that end.
    - Periods are clipped to what the data covers and to the query date.
    Returns (start, end, note). note explains anything the user should know.
    """
    first = table["month"].min()
    latest = table["month"].max()
    complete = table.loc[table["month_complete"].astype(bool), "month"]
    last_complete = complete.max() if len(complete) else latest
    note = None

    if last_n_months:
        end = last_complete
        start = shift_month(end, -(int(last_n_months) - 1))
        note = f"Used the latest {int(last_n_months)} full months of data."
    elif not start and not end:
        end = last_complete
        start = shift_month(end, -(default_months - 1))
        note = f"No exact period asked; used the latest {default_months} full months."
    else:
        start = start or first
        end = end or latest
        if start > end:  # written the wrong way round
            start, end = end, start

    # Nothing to show for a period wholly outside the data: keep the period
    # as asked, so the result has 0 deals and the note says why.
    if start > latest:
        return start, end, f"Asked about {start} onwards, but the data only goes up to {latest}."
    if end < first:
        return start, end, f"Asked about up to {end}, but the data only starts in {first}."

    # Otherwise clip to the data and to the query date.
    end = min(end, latest)
    if query_date:
        end = min(end, str(query_date)[:7])
    start = max(start, first)
    return start, end, note


def summarise(table, town, flat_type, start, end):
    """Median, average, lowest and highest price and the number of deals."""
    rows = table[(table["month"] >= start) & (table["month"] <= end)]
    if town != ALL:
        rows = rows[rows["town"] == town]
    if flat_type != ALL:
        rows = rows[rows["flat_type"] == flat_type]

    if rows.empty:
        return {"median_price": None, "mean_price": None, "min_price": None,
                "max_price": None, "n_deals": 0}
    prices = rows["resale_price"]
    return {
        "median_price": int(round(prices.median())),
        "mean_price": int(round(prices.mean())),
        "min_price": int(prices.min()),
        "max_price": int(prices.max()),
        "n_deals": int(len(rows)),
    }
