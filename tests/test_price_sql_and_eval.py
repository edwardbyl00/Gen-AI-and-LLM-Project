"""Tests for approach B (text-to-SQL) and the A vs B evaluation. No API key needed."""

import pandas as pd
import pytest

from agents.price.data import ALL
from agents.price.sql_agent import (
    UnsafeQueryError, check_sql, describe_query, make_connection, price_agent_sql, run_sql,
)
from evaluation.evaluate_price_agents import evaluate, figure_is_correct, summarise


@pytest.fixture
def table():
    rows = []
    for month in ["2025-09", "2025-10", "2026-01", "2026-09", "2026-10"]:
        rows += [
            {"month": month, "town": "TAMPINES", "flat_type": "4 ROOM", "resale_price": 600000},
            {"month": month, "town": "TAMPINES", "flat_type": "4 ROOM", "resale_price": 700000},
            {"month": month, "town": "BEDOK", "flat_type": "3 ROOM", "resale_price": 400000},
        ]
    df = pd.DataFrame(rows)
    df["month_complete"] = df["month"] < "2026-10"
    return df


def fake_sql(sql):
    return lambda question, query_date, table, default_months, client=None, usage_log=None: sql


# ---------- safety ----------

@pytest.mark.parametrize("bad", [
    "DELETE FROM resale",
    "SELECT * FROM resale; DROP TABLE resale",
    "UPDATE resale SET resale_price = 0",
    "PRAGMA table_info(resale)",
])
def test_unsafe_queries_are_rejected(bad):
    with pytest.raises(UnsafeQueryError):
        check_sql(bad)


def test_authorizer_blocks_other_tables(table):
    conn = make_connection(table)
    with pytest.raises(Exception):
        run_sql(conn, "SELECT name FROM sqlite_master")


def test_safe_query_runs(table):
    rows = run_sql(make_connection(table),
                   "SELECT month, town, flat_type, resale_price FROM resale "
                   "WHERE town = 'BEDOK';")
    assert len(rows) == 5


# ---------- reading filters back ----------

def test_describe_query():
    sql = ("SELECT month, town, flat_type, resale_price FROM resale WHERE town = 'Tampines' "
           "AND flat_type = '4 ROOM' AND month BETWEEN '2025-10' AND '2026-09'")
    assert describe_query(sql) == {"town": "TAMPINES", "flat_type": "4 ROOM",
                                   "period_start": "2025-10", "period_end": "2026-09"}


def test_describe_query_without_town():
    assert describe_query("SELECT * FROM resale WHERE flat_type = '5 ROOM'")["town"] == ALL


# ---------- the agent ----------

def test_sql_agent_matches_approach_a_figures(table):
    sql = ("SELECT month, town, flat_type, resale_price FROM resale WHERE town = 'TAMPINES' "
           "AND flat_type = '4 ROOM' AND month BETWEEN '2025-10' AND '2026-09'")
    out = price_agent_sql("x", "2026-10-25", write_fn=fake_sql(sql), table=table)
    assert (out["median_price"], out["mean_price"], out["min_price"], out["max_price"],
            out["n_deals"]) == (650000, 650000, 600000, 700000, 6)
    assert out["approach"] == "B_text_to_sql" and out["filters"]["sql"] == sql


def test_sql_agent_refuses_unsafe_query(table):
    out = price_agent_sql("x", "2026-10-25", write_fn=fake_sql("DROP TABLE resale"),
                          table=table)
    assert out["n_deals"] == 0 and "could not be run safely" in out["note"]


def test_sql_agent_no_matches(table):
    sql = ("SELECT month, town, flat_type, resale_price FROM resale WHERE town = 'TENGAH' "
           "AND month BETWEEN '2025-10' AND '2026-09'")
    out = price_agent_sql("x", "2026-10-25", write_fn=fake_sql(sql), table=table)
    assert out["n_deals"] == 0 and out["median_price"] is None


# ---------- evaluation ----------

def test_figure_tolerance():
    assert figure_is_correct("median", 650000, 655000)       # within 1%
    assert not figure_is_correct("median", 600000, 655000)
    assert figure_is_correct("count", 6, 6.0)
    assert not figure_is_correct("count", 7, 6)
    assert not figure_is_correct("median", None, 655000)


def test_evaluate_scores_each_system():
    rows = [
        {"question_id": "Q1", "question": "4-room Tampines recently?", "difficulty": "clear",
         "asks": "median", "query_date": "2026-10-25", "exp_town": "TAMPINES",
         "exp_flat_type": "4 ROOM", "exp_period_start": "2025-10", "exp_period_end": "2026-09",
         "true_median": "650000", "true_mean": "", "true_min": "", "true_max": "",
         "true_count": "6"},
        {"question_id": "Q2", "question": "4-room Tampines in 2027?", "difficulty": "future",
         "asks": "none", "query_date": "2026-10-25", "exp_town": "TAMPINES",
         "exp_flat_type": "4 ROOM", "exp_period_start": "2027-01", "exp_period_end": "2027-12",
         "true_median": "", "true_mean": "", "true_min": "", "true_max": "",
         "true_count": "0"},
    ]
    answers = {
        "4-room Tampines recently?": {
            "town": "TAMPINES", "flat_type": "4 ROOM", "period_start": "2025-10",
            "period_end": "2026-09", "median_price": 650000, "mean_price": 650000,
            "min_price": 600000, "max_price": 700000, "n_deals": 6},
        "4-room Tampines in 2027?": {
            "town": "TAMPINES", "flat_type": "4 ROOM", "period_start": "2027-01",
            "period_end": "2027-12", "median_price": None, "mean_price": None,
            "min_price": None, "max_price": None, "n_deals": 0},
    }

    def right(q, d, usage_log):          # an agent that gets everything right
        return answers[q]

    def guesser(q, d, usage_log):        # a chatbot that always invents a figure
        return {"median_price": 500000, "mean_price": 500000, "min_price": None,
                "max_price": None, "n_deals": None, "declined": False}

    def broken(q, d, usage_log):         # a system whose call fails
        raise RuntimeError("API down")

    summary = summarise(evaluate(rows, {"A": right, "chatbot": guesser, "B": broken}))
    assert summary["A"]["filters_correct"] == (2, 2)
    assert summary["A"]["figure_correct"] == (1, 1)
    assert summary["A"]["no_data_correct"] == (1, 1)
    assert summary["chatbot"]["figure_correct"] == (0, 1)
    assert summary["chatbot"]["no_data_correct"] == (0, 1)   # invented a figure
    assert summary["B"]["errors"] == 2
