"""Clean the HDB resale price data for the price agent (P1).

Input : data.gov.sg "Resale flat prices based on registration date from
        Jan-2017 onwards" (CSV), saved under data/raw/ (git-ignored)
Output: data/cleaned/hdb_resale_prices.csv.gz, one row per resale deal

Paths come from config.yaml (price_agent section), never typed into code.

Run from the project root:  python -m scripts.clean_prices
"""

import re
from pathlib import Path

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = PROJECT_ROOT / "config.yaml"


def lease_to_years(text):
    """'61 years 04 months' -> 61.33 and '57 years' -> 57.0"""
    match = re.match(r"^(\d+) years?(?: (\d+) months?)?$", str(text).strip())
    if match is None:
        raise ValueError(f"Unexpected remaining_lease format: {text!r}")
    years = int(match.group(1))
    months = int(match.group(2) or 0)
    return round(years + months / 12, 2)


def clean(raw):
    """Return the cleaned table. Nothing is dropped (see the notes below)."""
    df = raw.copy()

    # Month stays as "YYYY-MM" text: it sorts correctly and compares simply.
    df["month"] = pd.to_datetime(df["month"], format="%Y-%m").dt.strftime("%Y-%m")

    # Remaining lease text -> a number of years, so it can be compared.
    df["remaining_lease_years"] = df["remaining_lease"].apply(lease_to_years)

    # "10 TO 12" -> two numbers, so "high floor" questions can be answered.
    floors = df["storey_range"].str.extract(r"^(\d+) TO (\d+)$").astype(int)
    df["storey_low"] = floors[0]
    df["storey_high"] = floors[1]

    # Names are already consistent in the source; only trim stray spaces.
    for col in ["town", "flat_type", "flat_model", "street_name", "block"]:
        df[col] = df[col].astype(str).str.strip()

    # The newest month is usually still filling up, so mark it incomplete.
    # "Recently" then uses full months only.
    df["month_complete"] = df["month"] < df["month"].max()

    # Look-alike rows are kept: the data has no unit number, so two real
    # sales in the same block, floor band, month and price look identical.

    return df[[
        "month", "month_complete", "town", "flat_type", "flat_model",
        "block", "street_name", "storey_range", "storey_low", "storey_high",
        "floor_area_sqm", "lease_commence_date", "remaining_lease_years",
        "resale_price",
    ]]


def main():
    with open(CONFIG_FILE) as f:
        settings = (yaml.safe_load(f) or {}).get("price_agent", {})
    raw_path = PROJECT_ROOT / settings["raw_data"]
    out_path = PROJECT_ROOT / settings["cleaned_data"]

    raw = pd.read_csv(raw_path, dtype={"block": str})
    cleaned = clean(raw)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned.to_csv(out_path, index=False)

    print(f"Rows in : {len(raw)}")
    print(f"Rows out: {len(cleaned)}")
    print(f"Months  : {cleaned['month'].min()} to {cleaned['month'].max()} "
          "(latest month marked incomplete)")
    print(f"Saved   : {out_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
