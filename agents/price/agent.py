"""P1 price agent: question in, exact resale price figures out.

Output shape: Docs/p2_supervisor_contract.md, section A4 (price agent).

How it works (approach A, "filter tool"):
  1. The LLM turns the question into filters: town, flat type, period.
  2. Code checks the filters and turns vague periods into exact months.
  3. Code calculates median, lowest and highest price and the deal count.
The LLM never calculates prices, so the numbers are always exact.
"""

from datetime import date

from agents.price.data import (
    ALL, load_price_settings, load_price_table, resolve_period, summarise,
)
from agents.price.extract import extract_filters

APPROACH = "A_filter_tool"


def check_value(value, allowed):
    """Keep a value only if it is in the data; anything else means 'ALL'."""
    if value is None:
        return ALL
    value = str(value).strip().upper()
    return value if value in allowed else ALL


def price_agent(question, query_date=None, client=None, extract_fn=None,
                table=None, usage_log=None):
    """Answer the price part of a question with exact figures.

    Returns the contract fields (town, flat_type, period_start, period_end,
    median_price, min_price, max_price, n_deals, data_as_of) plus:
      mean_price : the average price, for questions that ask for an average
      approach : which price agent approach produced this
      filters  : what the LLM extracted, for the step log
      note     : anything synthesis should tell the user, or None
    town or flat_type is "ALL" when the question names none.
    """
    query_date = query_date or date.today().isoformat()
    table = table if table is not None else load_price_table()
    default_months = load_price_settings().get("default_months", 12)
    extract_fn = extract_fn or extract_filters

    filters = extract_fn(question, query_date, table, client=client, usage_log=usage_log)
    town = check_value(filters.get("town"), set(table["town"]))
    flat_type = check_value(filters.get("flat_type"), set(table["flat_type"]))
    start, end, note = resolve_period(
        table, filters.get("period_start"), filters.get("period_end"),
        default_months, query_date, filters.get("last_n_months"))

    result = {
        "town": town,
        "flat_type": flat_type,
        "period_start": start,
        "period_end": end,
        **summarise(table, town, flat_type, start, end),
        "data_as_of": table["month"].max(),
        "approach": APPROACH,
        "filters": filters,
        "note": note,
    }
    if result["n_deals"] == 0 and note is None:
        result["note"] = "No resale deals match these filters in this period."
    return result


# Try the price agent when this file is run directly.
if __name__ == "__main__":
    import json
    import sys

    question = " ".join(sys.argv[1:]) or "What did 4-room flats in Tampines sell for recently?"
    print(json.dumps(price_agent(question), indent=2))
