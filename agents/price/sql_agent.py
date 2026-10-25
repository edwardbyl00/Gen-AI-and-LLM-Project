"""Approach B: text-to-SQL.

The LLM writes a SQL query that selects the matching resale deals. Code then
checks the query is a safe, read-only SELECT on the resale table, runs it on
an in-memory copy of the price data, and calculates the figures itself.

Compared with approach A (a fixed form of filters), the LLM has more freedom:
it can express any filter SQL allows, but it can also write a wrong or
unsafe query. Comparing the two is P1's approach study.
"""

import json
import re
import sqlite3
from datetime import date
from pathlib import Path

from agents.price.data import (
    ALL, load_price_settings, load_price_table, shift_month,
)
from agents.supervisor.router import load_settings, make_client

APPROACH = "B_text_to_sql"
PROMPT_FILE = Path(__file__).parent / "prompts" / "price_sql_v1.md"
COLUMNS = ["month", "town", "flat_type", "resale_price"]

SQL_SCHEMA = {
    "name": "price_sql",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {"sql": {"type": "string"}},
        "required": ["sql"],
        "additionalProperties": False,
    },
}


class UnsafeQueryError(Exception):
    """The LLM's query is not a single read-only SELECT on the resale table."""


class PriceSQLReplyError(Exception):
    """The model replied, but with no usable content (e.g. a refusal)."""


# ---------- safety ----------

def check_sql(sql):
    """Allow exactly one SELECT statement. Returns the cleaned query."""
    query = sql.strip().rstrip(";").strip()
    if ";" in query:
        raise UnsafeQueryError("More than one statement.")
    if not re.match(r"(?is)^select\s", query):
        raise UnsafeQueryError("Not a SELECT statement.")
    if re.search(r"(?i)\b(insert|update|delete|drop|alter|create|attach|pragma|replace)\b",
                 query):
        raise UnsafeQueryError("Contains a statement that changes data.")
    return query


def _authorizer(action, arg1, arg2, db_name, trigger):
    """SQLite permission check: only reading the resale table is allowed."""
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION}
    if action in allowed:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and arg1 == "resale":
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def make_connection(table):
    """An in-memory, read-only copy of the price table."""
    conn = sqlite3.connect(":memory:")
    table[COLUMNS].to_sql("resale", conn, index=False)
    conn.set_authorizer(_authorizer)
    return conn


def run_sql(conn, sql):
    """Run a checked query. Returns a list of (month, town, flat_type, price) rows."""
    return conn.execute(check_sql(sql)).fetchall()


# ---------- the LLM call ----------

def periods_for_prompt(table, default_months):
    """The exact months the prompt gives for 'recently' and 'last N months'."""
    complete = table.loc[table["month_complete"].astype(bool), "month"]
    last_full = complete.max() if len(complete) else table["month"].max()
    return last_full, shift_month(last_full, -(default_months - 1))


def write_sql(question, query_date, table, default_months, client=None, usage_log=None):
    """Ask the LLM for the query. Returns the SQL text."""
    settings = load_settings()
    client = client or make_client(settings.get("timeout_seconds"))
    last_full, recent_start = periods_for_prompt(table, default_months)
    prompt = (PROMPT_FILE.read_text()
              .replace("{today}", query_date)
              .replace("{data_start}", table["month"].min())
              .replace("{data_end}", table["month"].max())
              .replace("{last_full_month}", last_full)
              .replace("{recent_start}", recent_start)
              .replace("{towns}", "\n".join(sorted(table["town"].unique())))
              .replace("{flat_types}", "\n".join(sorted(table["flat_type"].unique()))))

    request = {
        "model": settings["model"],
        "messages": [{"role": "system", "content": prompt},
                     {"role": "user", "content": question}],
        "response_format": {"type": "json_schema", "json_schema": SQL_SCHEMA},
    }
    for key, api_key in (("temperature", "temperature"), ("seed", "seed"),
                         ("max_output_tokens", "max_completion_tokens")):
        if settings.get(key) is not None:
            request[api_key] = settings[key]

    response = client.chat.completions.create(**request)
    if usage_log is not None:
        usage = getattr(response, "usage", None)
        usage_log.append({"step": "price_sql",
                          "input_tokens": getattr(usage, "prompt_tokens", None),
                          "output_tokens": getattr(usage, "completion_tokens", None)})
    message = response.choices[0].message
    if message.content is None:
        raise PriceSQLReplyError(
            f"No content in reply (refusal: {getattr(message, 'refusal', None)})")
    return json.loads(message.content)["sql"]


# ---------- reading the period and filters back from the query ----------

def describe_query(sql):
    """Read town, flat type and period back out of the query, for the contract
    fields and so the filters can be scored against approach A's."""
    def value(column):
        found = re.findall(rf"(?i)\b{column}\s*=\s*'([^']*)'", sql)
        return found[0].upper() if len(found) == 1 else ALL
    period = re.search(r"(?i)\bmonth\s+between\s+'(\d{4}-\d{2})'\s+and\s+'(\d{4}-\d{2})'", sql)
    start, end = period.groups() if period else (None, None)
    return {"town": value("town"), "flat_type": value("flat_type"),
            "period_start": start, "period_end": end}


# ---------- the agent ----------

def price_agent_sql(question, query_date=None, client=None, write_fn=None,
                    table=None, usage_log=None):
    """Approach B. Same output shape as approach A's price_agent()."""
    query_date = query_date or date.today().isoformat()
    table = table if table is not None else load_price_table()
    default_months = load_price_settings().get("default_months", 12)
    write_fn = write_fn or write_sql

    sql = write_fn(question, query_date, table, default_months,
                   client=client, usage_log=usage_log)
    described = describe_query(sql)
    base = {**described, "data_as_of": table["month"].max(), "approach": APPROACH,
            "filters": {"sql": sql}}

    try:
        rows = run_sql(make_connection(table), sql)
    except (UnsafeQueryError, sqlite3.Error) as error:
        return {**base, "median_price": None, "mean_price": None, "min_price": None,
                "max_price": None, "n_deals": 0,
                "note": f"The generated query could not be run safely ({error})."}

    prices = sorted(r[3] for r in rows)
    if not prices:
        return {**base, "median_price": None, "mean_price": None, "min_price": None,
                "max_price": None, "n_deals": 0,
                "note": "No resale deals match these filters in this period."}

    n = len(prices)
    median = prices[n // 2] if n % 2 else (prices[n // 2 - 1] + prices[n // 2]) / 2
    return {
        **base,
        "median_price": int(round(median)),
        "mean_price": int(round(sum(prices) / n)),
        "min_price": int(prices[0]),
        "max_price": int(prices[-1]),
        "n_deals": n,
        "note": None,
    }
