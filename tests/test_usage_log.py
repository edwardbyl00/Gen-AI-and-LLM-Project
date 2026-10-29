"""CSV consumption accounting and public entry-point integration; no API calls."""

import csv
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agents.graph.graph import build_graph, run
from agents.supervisor import usage_log
from agents.supervisor.pipeline import handle_question


def settings(tmp_path):
    return {"usage_logging": {"enabled": True, "directory": str(tmp_path / "usage")},
            "supervisor": {"decompose": True},
            "llm": {"model": "fixture-model", "pricing": {"input_per_1m": 2.5, "output_per_1m": 15}}}


def read(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def fixture_bundle(question="Question, with comma and Unicode ✓"):
    return {"question": question, "variant": "B_decomposition", "routing": {"route": "both"},
            "usage": [
                {"step": "router", "input_tokens": 100, "output_tokens": 10},
                {"step": "policy_assessor", "calls": 2, "input_tokens": 200, "output_tokens": 20,
                 "task_id": "policy_1", "attempt": 1},
                {"step": "synthesis", "input_tokens": 100, "output_tokens": 10},
                {"step": "synthesis", "input_tokens": 100, "output_tokens": 10}],
            "seconds": 4.5, "attempts": 1, "self_check": {"verdict": "weak"},
            "steps": [], "agent_errors": {}}


def test_csv_totals_aggregated_calls_and_appending(tmp_path):
    config = settings(tmp_path)
    info = usage_log.append_run(fixture_bundle(), "graph", config=config)
    second = usage_log.append_run(fixture_bundle("Second question"), "supervisor", config=config)
    rows, calls = read(info["summary_csv"]), read(info["calls_csv"])
    assert len(rows) == 2 and len(calls) == 8
    assert info["run_id"] != second["run_id"]
    assert rows[0]["question"] == fixture_bundle()["question"]
    assert rows[0]["model_calls"] == "5" and rows[0]["total_tokens"] == "550"
    assert float(rows[0]["estimated_cost_usd"]) == 0.002
    assert rows[0]["self_check"] == "weak" and rows[0]["usage_incomplete"] == "False"
    assert rows[0]["logged_at_sgt"].endswith("+08:00")
    assert calls[1]["model_calls"] == "2" and calls[1]["task_id"] == "policy_1"
    assert [c["attempt"] for c in calls[2:4]] == ["1", "2"]
    assert Path(info["summary_csv"]).read_bytes().count(b'\xef\xbb\xbf') == 1


def test_unknown_usage_is_blank_not_zero_and_errors_are_retained(tmp_path):
    bundle = fixture_bundle()
    bundle["usage"] = [{"step": "router", "input_tokens": None, "output_tokens": None}]
    info = usage_log.append_run(bundle, "graph", config=settings(tmp_path), error="Connection failed")
    row = read(info["summary_csv"])[0]
    assert row["status"] == "failed" and row["usage_incomplete"] == "True"
    assert row["estimated_cost_usd"] == row["total_tokens"] == ""
    assert read(info["calls_csv"])[0]["estimated_cost_usd"] == ""
    assert "Connection failed" in row["notes"]


def test_spreadsheet_formula_text_is_escaped(tmp_path):
    info = usage_log.append_run(fixture_bundle('=1+1'), "graph", config=settings(tmp_path))
    assert read(info["summary_csv"])[0]["question"] == "'=1+1"


def test_existing_header_is_checked_before_writing(tmp_path):
    config = settings(tmp_path)
    folder = tmp_path / "usage"
    folder.mkdir()
    (folder / "runs.csv").write_text("wrong,header\n")
    with pytest.raises(ValueError, match="header mismatch"):
        usage_log.append_run(fixture_bundle(), "graph", config=config)
    assert not (folder / "calls.csv").exists()


def test_concurrent_runs_keep_one_header_and_correct_rows(tmp_path):
    config = settings(tmp_path)
    with ThreadPoolExecutor(max_workers=6) as pool:
        infos = list(pool.map(lambda index: usage_log.append_run(
            fixture_bundle(f"Question {index}"), "graph", config=config), range(18)))
    rows = read(infos[0]["summary_csv"])
    assert len(rows) == len({r["run_id"] for r in rows}) == 18
    assert len(read(infos[0]["calls_csv"])) == 72


def test_trace_import_is_explicit_and_idempotent(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(usage_log, "load_config", lambda: settings(tmp_path))
    trace = tmp_path / "trace.json"
    trace.write_text(json.dumps(fixture_bundle()))
    first = usage_log.import_trace(trace, "graph")
    second = usage_log.import_trace(trace, "graph")
    assert first["written"] and not second["written"]
    assert len(read(first["summary_csv"])) == 1
    assert read(first["summary_csv"])[0]["source"] == "trace_import"


def route(question, today=None, usage_log=None):
    usage_log.append({"step": "router", "input_tokens": 20, "output_tokens": 3})
    return {"route": "none", "check_premise": False, "answerable": False, "reason": "Fixture"}, []


def synth(bundle, usage_log=None):
    usage_log.append({"step": "synthesis", "input_tokens": 30, "output_tokens": 5})
    return {"answer": "Fixture", "declined": True, "cited": [], "events": []}


def test_both_public_entry_points_log_once_without_extra_model_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(usage_log, "load_config", lambda: settings(tmp_path))
    first = handle_question("Supervisor question", route_fn=route, synth_fn=lambda bundle: synth(bundle, bundle["usage"]),
                            decompose=False)
    app = build_graph(route_fn=route, price_fn=lambda *a, **kw: {}, policy_fn=lambda *a, **kw: {},
        synth_fn=synth, decompose=False, self_check_settings={"llm_check": False, "max_retries": 1})
    second = run("Graph question", app=app, decompose=False)
    rows = read(first["usage_tracking"]["summary_csv"])
    assert [r["pipeline"] for r in rows] == ["supervisor", "graph"]
    assert all(r["model_calls"] == "2" for r in rows)
    assert first["usage_tracking"]["run_id"] != second["usage_tracking"]["run_id"]
    assert len(read(first["usage_tracking"]["calls_csv"])) == 4


def test_failed_pipeline_logs_reported_usage_and_keeps_original_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(usage_log, "load_config", lambda: settings(tmp_path))
    def broken(question, **kwargs):
        kwargs["usage_log"].append({"step": "router", "input_tokens": 10, "output_tokens": 2})
        raise ValueError("original error")
    with pytest.raises(ValueError, match="original error"):
        handle_question("Bad question", route_fn=broken, decompose=False)
    row = read(tmp_path / "usage/runs.csv")[0]
    assert row["status"] == "failed" and row["input_tokens"] == "10"
    assert float(row["estimated_cost_usd"]) > 0 and row["usage_incomplete"] == "True"


def test_logging_can_be_disabled_per_request(tmp_path, monkeypatch):
    monkeypatch.setattr(usage_log, "load_config", lambda: settings(tmp_path))
    handle_question("Do not save", route_fn=route, synth_fn=lambda b: synth(b, b["usage"]),
                    decompose=False, log_usage=False)
    assert not (tmp_path / "usage").exists()


def test_logging_io_failure_does_not_replace_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(usage_log, "load_config", lambda: settings(tmp_path))
    def denied(*args, **kwargs):
        raise PermissionError("Cannot write log")
    monkeypatch.setattr(usage_log, "append_run", denied)
    with pytest.warns(RuntimeWarning, match="could not be saved"):
        result = handle_question("Question", route_fn=route, synth_fn=lambda b: synth(b, b["usage"]), decompose=False)
    assert result["answer"]["answer"] == "Fixture"
