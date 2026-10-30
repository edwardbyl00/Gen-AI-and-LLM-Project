"""Price adapter integration: real calculations, with model calls replaced."""

import csv
import gzip
from pathlib import Path

import pandas as pd
import pytest

from agents.price import agent as price_module
from agents.price import run_price_agent
from agents.price.sql_agent import UnsafeQueryError, check_sql
from agents.supervisor.adapters import get_price_agent, price_real
from agents.supervisor.pipeline import handle_question
from agents.supervisor.synthesis import build_context


def test_real_adapter_forwards_question_and_date(monkeypatch):
    import agents.price

    calls = []
    result = {"town": "TOA PAYOH", "n_deals": 12}

    def fake(question, query_date, usage_log=None):
        calls.append((question, query_date))
        return result

    monkeypatch.setattr(agents.price, "run_price_agent", fake)
    assert get_price_agent({"price": "real"})("How many sales?", "2026-10-25") is result
    assert calls == [("How many sales?", "2026-10-25")]
    assert get_price_agent() is price_real


def test_pipeline_uses_real_transactions(monkeypatch):
    def filters(question, query_date, table, **kwargs):
        return {"town": "TOA PAYOH", "flat_type": "4 ROOM",
                "period_start": "2024-01", "period_end": "2024-12"}

    monkeypatch.setattr(price_module, "extract_filters", filters)
    routing = {"route": "price", "check_premise": False,
               "answerable": True, "reason": "Historical transaction count"}
    captured = {}

    def synthesise(bundle):
        captured["context"], _ = build_context(bundle)
        return {"answer": "Test", "declined": False, "cited": [],
                "sources": [], "events": []}

    bundle = handle_question(
        "How many 4-room resale flats were sold in Toa Payoh in 2024?",
        today="2026-10-25", route_fn=lambda *args, **kwargs: (routing, []),
        synth_fn=synthesise, strict=True, decompose=False,
    )
    # Independently count the source rows without using agent calculations.
    path = Path(__file__).resolve().parents[1] / "data/cleaned/hdb_resale_prices.csv.gz"
    with gzip.open(path, "rt", newline="", encoding="utf-8") as source:
        expected = sum(1 for row in csv.DictReader(source)
                       if row["town"] == "TOA PAYOH" and row["flat_type"] == "4 ROOM"
                       and "2024-01" <= row["month"] <= "2024-12")
    result = bundle["price_result"]
    assert expected > 0 and result["n_deals"] == expected
    assert result["approach"] == "A_filter_tool"
    assert not result.get("stub") and bundle["agent_errors"] == {}
    assert bundle["policy_result"] is None
    assert "mean_price:" in captured["context"]
    assert not next(step for step in bundle["steps"] if step["step"] == "price_agent")["stub"]


def test_future_price_note_reaches_synthesis(monkeypatch):
    monkeypatch.setattr(price_module, "extract_filters", lambda *args, **kwargs: {
        "town": "TOA PAYOH", "flat_type": "4 ROOM",
        "period_start": "2099-01", "period_end": "2099-12",
    })
    result = price_real("What will flats cost in 2099?", "2026-10-25")
    assert result["n_deals"] == 0 and result["median_price"] is None
    context, _ = build_context({
        "question": "What will flats cost in 2099?",
        "routing": {"route": "price", "check_premise": False, "answerable": False},
        "price_result": result,
    })
    assert result["note"] in context


def test_sql_approach_remains_selectable_and_rejects_writes(monkeypatch):
    import agents.price

    monkeypatch.setattr(agents.price, "load_price_settings", lambda: {"approach": "B"})
    table = pd.DataFrame({"month": ["2024-01", "2024-01"],
                          "town": ["TOA PAYOH"] * 2, "flat_type": ["4 ROOM"] * 2,
                          "resale_price": [500000, 700000], "month_complete": [True] * 2})
    result = run_price_agent(
        "Prices?", "2026-10-25", table=table,
        write_fn=lambda *args, **kwargs: (
            "SELECT month, town, flat_type, resale_price FROM resale "
            "WHERE town = 'TOA PAYOH' AND flat_type = '4 ROOM' "
            "AND month BETWEEN '2024-01' AND '2024-12'"),
    )
    assert result["approach"] == "B_text_to_sql"
    assert result["n_deals"] == 2 and result["median_price"] == 600000
    with pytest.raises(UnsafeQueryError):
        check_sql("DELETE FROM resale")
