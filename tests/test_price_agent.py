"""Tests for the P1 price agent. No API key needed: the LLM is replaced by a fake."""

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from agents.price.agent import price_agent
from agents.price.data import ALL, resolve_period, shift_month, summarise
from agents.price.extract import extract_filters, filter_schema
from scripts.clean_prices import clean, lease_to_years

CONTRACT_FIELDS = {
    "town", "flat_type", "period_start", "period_end", "median_price",
    "min_price", "max_price", "n_deals", "data_as_of",
}


@pytest.fixture
def table():
    """A tiny price table: Tampines and Bedok, 2025-09 to 2026-10 (2026-10 incomplete)."""
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


def fake_extract(**filters):
    """Return a stand-in for the LLM that always gives these filters."""
    base = {"town": None, "flat_type": None, "period_start": None,
            "period_end": None, "last_n_months": None, "unmatched_place": None,
            "period_words": None}
    base.update(filters)
    return lambda question, query_date, table, client=None, usage_log=None: base


# ---------- cleaning ----------

def test_lease_to_years_handles_both_formats():
    assert lease_to_years("61 years 04 months") == 61.33
    assert lease_to_years("62 years 01 month") == 62.08
    assert lease_to_years("57 years") == 57.0


def test_lease_to_years_rejects_unknown_format():
    with pytest.raises(ValueError):
        lease_to_years("about sixty years")


def test_clean_keeps_every_row_and_marks_latest_month():
    raw = pd.DataFrame({
        "month": ["2026-09", "2026-10", "2026-10"],
        "town": ["TAMPINES "] * 3, "flat_type": ["4 ROOM"] * 3,
        "block": ["1", "2", "2"], "street_name": ["ST"] * 3,
        "storey_range": ["10 TO 12", "01 TO 03", "01 TO 03"],
        "floor_area_sqm": [90.0] * 3, "flat_model": ["Model A"] * 3,
        "lease_commence_date": [1990] * 3,
        "remaining_lease": ["63 years", "62 years 11 months", "62 years 11 months"],
        "resale_price": [600000.0, 610000.0, 610000.0],
    })
    out = clean(raw)
    assert len(out) == 3                      # look-alike rows are kept
    assert out["town"].iloc[0] == "TAMPINES"  # stray space trimmed
    assert list(out["month_complete"]) == [True, False, False]
    assert out["storey_low"].iloc[0] == 10 and out["storey_high"].iloc[0] == 12


# ---------- period rules ----------

def test_shift_month_crosses_year():
    assert shift_month("2026-09", -11) == "2025-10"


def test_vague_period_uses_latest_full_months(table):
    start, end, note = resolve_period(table, None, None, 12)
    assert (start, end) == ("2025-10", "2026-09")   # skips incomplete 2026-10
    assert "12 full months" in note


def test_last_n_months_counts_back_from_latest_full_month(table):
    start, end, note = resolve_period(table, None, None, 12, last_n_months=6)
    assert (start, end) == ("2026-04", "2026-09")
    assert "6 full months" in note


def test_mean_differs_from_median_when_skewed():
    df = pd.DataFrame({"month": ["2026-01"] * 3, "town": ["BISHAN"] * 3,
                       "flat_type": ["5 ROOM"] * 3,
                       "resale_price": [800000, 900000, 1600000]})
    stats = summarise(df, "BISHAN", "5 ROOM", "2026-01", "2026-01")
    assert stats["median_price"] == 900000 and stats["mean_price"] == 1100000


def test_open_ended_period(table):
    start, end, _ = resolve_period(table, "2026-01", None, 12)
    assert (start, end) == ("2026-01", "2026-10")


def test_future_period_is_flagged(table):
    start, end, note = resolve_period(table, "2027-01", "2027-12", 12)
    assert (start, end) == ("2027-01", "2027-12")   # kept as asked, not stretched
    assert "only goes up to 2026-10" in note


def test_future_period_returns_no_deals(table):
    result = price_agent("x", "2026-10-25",
                         extract_fn=fake_extract(town="TAMPINES", flat_type="4 ROOM",
                                                 period_start="2027-01", period_end="2027-12"),
                         table=table)
    assert result["n_deals"] == 0 and result["median_price"] is None
    assert "only goes up to" in result["note"]


def test_period_capped_at_query_date(table):
    _, end, _ = resolve_period(table, "2025-09", "2026-10", 12, query_date="2026-01-15")
    assert end == "2026-01"


# ---------- price numbers ----------

def test_summarise_is_exact(table):
    stats = summarise(table, "TAMPINES", "4 ROOM", "2025-10", "2026-09")
    assert stats == {"median_price": 650000, "mean_price": 650000, "min_price": 600000,
                     "max_price": 700000, "n_deals": 6}


def test_summarise_all_towns(table):
    stats = summarise(table, ALL, ALL, "2025-09", "2025-09")
    assert stats["n_deals"] == 3 and stats["min_price"] == 400000


def test_summarise_no_matches(table):
    stats = summarise(table, "BISHAN", "5 ROOM", "2025-09", "2026-10")
    assert stats == {"median_price": None, "mean_price": None, "min_price": None,
                     "max_price": None, "n_deals": 0}


# ---------- full agent ----------

def test_price_agent_returns_contract_fields(table):
    result = price_agent("4-room in Tampines recently?", "2026-10-25",
                         extract_fn=fake_extract(town="TAMPINES", flat_type="4 ROOM"),
                         table=table)
    assert CONTRACT_FIELDS <= set(result)
    assert result["median_price"] == 650000
    assert (result["period_start"], result["period_end"]) == ("2025-10", "2026-09")
    assert result["data_as_of"] == "2026-10"


def test_price_agent_ignores_values_not_in_data(table):
    result = price_agent("x", "2026-10-25",
                         extract_fn=fake_extract(town="ATLANTIS", flat_type="4 room"),
                         table=table)
    assert result["town"] == ALL            # unknown town falls back to ALL
    assert result["flat_type"] == "4 ROOM"  # case is fixed


def test_price_agent_explains_empty_result(table):
    result = price_agent("x", "2026-10-25",
                         extract_fn=fake_extract(town="BEDOK", flat_type="4 ROOM",
                                                 period_start="2026-01", period_end="2026-01"),
                         table=table)
    assert result["n_deals"] == 0 and "No resale deals" in result["note"]


# ---------- LLM call (with a fake client) ----------

class FakeClient:
    def __init__(self, reply):
        self.sent = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self.reply = reply

    def create(self, **request):
        self.sent = request
        message = SimpleNamespace(content=json.dumps(self.reply), refusal=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


def test_extract_filters_sends_schema_and_parses_reply(table):
    reply = {"town": "TAMPINES", "flat_type": "4 ROOM", "period_start": None,
             "period_end": None, "last_n_months": None, "unmatched_place": None,
             "period_words": "recently"}
    client = FakeClient(reply)
    out = extract_filters("4rm Tampines lately?", "2026-10-25", table, client=client)
    assert out == reply
    schema = client.sent["response_format"]["json_schema"]
    assert schema["strict"] is True
    assert "TAMPINES" in schema["schema"]["properties"]["town"]["enum"]
    assert "2026-10-25" in client.sent["messages"][0]["content"]


def test_filter_schema_allows_null_town():
    schema = filter_schema(["TAMPINES"], ["4 ROOM"])
    assert None in schema["schema"]["properties"]["town"]["enum"]


def test_unmatched_place_reports_no_deals_instead_of_all_towns(table):
    result = price_agent("5-room in Tengah?", "2026-10-25",
                         extract_fn=fake_extract(flat_type="5 ROOM", unmatched_place="Tengah"),
                         table=table)
    assert result["town"] == "TENGAH"
    assert result["n_deals"] == 0 and result["median_price"] is None
    assert "not one of the HDB towns" in result["note"]
