"""Append local, Excel-readable usage CSVs without making model calls."""

import argparse
import csv
import hashlib
import inspect
import json
import os
import tempfile
import threading
import time
import uuid
import warnings
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from agents.supervisor.router import CONFIG_FILE, PROJECT_ROOT

LEGACY_RUN_COLUMNS = [
    "logged_at_sgt", "run_id", "source", "pipeline", "variant", "question", "route",
    "model_calls", "input_tokens", "output_tokens", "total_tokens", "estimated_cost_usd",
    "seconds", "retry_cycles", "self_check", "status", "usage_incomplete", "configured_model",
    "input_usd_per_1m", "output_usd_per_1m", "notes",
]
RUN_COLUMNS = LEGACY_RUN_COLUMNS + ["policy_abstained", "policy_outcomes", "answer_declined"]
CALL_COLUMNS = [
    "logged_at_sgt", "run_id", "pipeline", "usage_entry", "stage", "task_id", "attempt",
    "model_calls", "input_tokens", "output_tokens", "total_tokens", "estimated_cost_usd",
]
_THREAD_LOCK = threading.Lock()


def load_config():
    return yaml.safe_load(CONFIG_FILE.read_text()) or {}


def _excel_safe(value):
    # Questions are user text, not spreadsheet formulas. Numbers stay numeric.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


@contextmanager
def _locked(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with _THREAD_LOCK, (directory / ".usage.lock").open("a+b") as stream:
        try:
            import fcntl
        except ImportError:  # Windows team environments
            import msvcrt
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _validate_header(path, columns, legacy_columns=None):
    if path.exists() and path.stat().st_size:
        with path.open(newline="", encoding="utf-8-sig") as stream:
            header = next(csv.reader(stream), None)
            if header != columns and (legacy_columns is None or header != legacy_columns):
                raise ValueError(f"Usage CSV header mismatch: {path}; choose a new logging directory")


def _upgrade_run_header(path):
    """Atomically extend the known old schema; historical outcomes stay unknown."""
    if not path.exists() or not path.stat().st_size:
        return
    temporary = None
    try:
        with path.open(newline="", encoding="utf-8-sig") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames != LEGACY_RUN_COLUMNS:
                return
            with tempfile.NamedTemporaryFile(mode="w", newline="", encoding="utf-8-sig",
                                             dir=path.parent, delete=False) as target:
                temporary = Path(target.name)
                writer = csv.DictWriter(target, fieldnames=RUN_COLUMNS)
                writer.writeheader()
                writer.writerows(reader)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _policy_outcomes(bundle):
    """Keep every logged policy attempt, including abstentions before retries."""
    outcomes = []
    attempts = {}
    for step in bundle.get("steps", []):
        if step.get("step") != "policy_agent" or not step.get("decision"):
            continue
        task_id = step.get("task_id", "policy")
        attempts[task_id] = attempts.get(task_id, 0) + 1
        outcomes.append({"task_id": task_id, "attempt": step.get("attempt", attempts[task_id]),
                         "decision": step["decision"], "reason": step.get("reason")})
    if outcomes:
        return outcomes
    # Saved traces from before step-level outcomes were recorded still hold
    # the final result, either per task or in the baseline policy_result.
    records = bundle.get("task_results")
    if records is None:
        records = [{"task": {"id": "policy", "agent": "policy"},
                    "result": bundle.get("policy_result")}]
    for record in records:
        result = record.get("result") or {}
        if record["task"]["agent"] == "policy" and result.get("decision"):
            outcomes.append({"task_id": record["task"]["id"], "attempt": record.get("attempt", 1),
                             "decision": result["decision"], "reason": result.get("reason")})
    return outcomes


def _append(path, columns, rows):
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8-sig" if new else "utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        if new:
            writer.writeheader()
        writer.writerows({k: _excel_safe(v) for k, v in row.items()} for row in rows)


def append_run(bundle, pipeline, *, config=None, source="live_run", run_id=None,
               error=None, elapsed=None):
    """One summary row plus one row per reported usage entry (some aggregate calls)."""
    config = config if config is not None else load_config()
    directory = PROJECT_ROOT / config.get("usage_logging", {}).get("directory", "logs/usage")
    directory = directory.resolve()
    summary_path, calls_path = directory / "runs.csv", directory / "calls.csv"
    run_id = run_id or uuid.uuid4().hex
    timestamp = datetime.now(ZoneInfo("Asia/Singapore")).isoformat(timespec="seconds")
    llm = config.get("llm", {})
    pricing = llm.get("pricing", {})
    input_rate, output_rate = pricing.get("input_per_1m"), pricing.get("output_per_1m")
    rates_known = all(isinstance(rate, (int, float)) and rate >= 0 for rate in (input_rate, output_rate))
    usage = bundle.get("usage", [])
    has_errors = bool(error or bundle.get("agent_errors") or any(s.get("error") for s in bundle.get("steps", [])))
    incomplete = not usage or has_errors or not rates_known or any(
        u.get("input_tokens") is None or u.get("output_tokens") is None for u in usage)
    total_input = sum(u.get("input_tokens") or 0 for u in usage)
    total_output = sum(u.get("output_tokens") or 0 for u in usage)
    input_known = any(u.get("input_tokens") is not None for u in usage)
    output_known = any(u.get("output_tokens") is not None for u in usage)

    def cost(input_tokens, output_tokens):
        return round((input_tokens * input_rate + output_tokens * output_rate) / 1_000_000, 6) if rates_known else ""

    review = bundle.get("self_check", {}).get("verdict", "")
    status = "failed" if error else "completed_with_errors" if has_errors else "completed"
    notes = [error] if error else []
    if incomplete:
        notes.append("Only reported usage is counted; missing usage/cost is unknown.")
    policy_outcomes = _policy_outcomes(bundle)
    row = {
        "logged_at_sgt": timestamp, "run_id": run_id, "source": source,
        "pipeline": pipeline, "variant": bundle.get("variant", ""),
        "question": bundle.get("question", ""), "route": bundle.get("routing", {}).get("route", ""),
        "model_calls": sum(u.get("calls", 1) for u in usage) if usage else "",
        "input_tokens": total_input if input_known else "", "output_tokens": total_output if output_known else "",
        "total_tokens": total_input + total_output if input_known or output_known else "",
        "estimated_cost_usd": cost(total_input, total_output) if input_known or output_known else "",
        "seconds": bundle.get("seconds", elapsed if elapsed is not None else ""),
        "retry_cycles": bundle.get("attempts", ""), "self_check": review,
        "status": status, "usage_incomplete": incomplete, "configured_model": llm.get("model", ""),
        "input_usd_per_1m": input_rate if input_rate is not None else "",
        "output_usd_per_1m": output_rate if output_rate is not None else "", "notes": " ".join(notes),
        "policy_abstained": any(o["decision"] == "ABSTAIN" for o in policy_outcomes)
            if policy_outcomes else "",
        "policy_outcomes": json.dumps(policy_outcomes, ensure_ascii=False) if policy_outcomes else "",
        "answer_declined": (bundle.get("answer") or {}).get("declined", ""),
    }
    detail_rows = []
    stage_attempts = {}
    for index, u in enumerate(usage, 1):
        stage = u.get("step", "unknown")
        stage_attempts[stage] = stage_attempts.get(stage, 0) + 1
        known_input, known_output = u.get("input_tokens"), u.get("output_tokens")
        detail_rows.append({
            "logged_at_sgt": timestamp, "run_id": run_id, "pipeline": pipeline, "usage_entry": index,
            "stage": stage, "task_id": u.get("task_id", ""),
            "attempt": u.get("attempt", stage_attempts[stage]), "model_calls": u.get("calls", 1),
            "input_tokens": known_input if known_input is not None else "",
            "output_tokens": known_output if known_output is not None else "",
            "total_tokens": (known_input or 0) + (known_output or 0)
                if known_input is not None or known_output is not None else "",
            "estimated_cost_usd": cost(known_input or 0, known_output or 0)
                if known_input is not None or known_output is not None else "",
        })
    with _locked(directory):
        _validate_header(summary_path, RUN_COLUMNS, LEGACY_RUN_COLUMNS)
        _validate_header(calls_path, CALL_COLUMNS)
        _upgrade_run_header(summary_path)
        # Importing the same saved trace twice must not count it twice.
        if source == "trace_import" and summary_path.exists():
            with summary_path.open(newline="", encoding="utf-8-sig") as stream:
                if any(r["run_id"] == run_id for r in csv.DictReader(stream)):
                    return {"run_id": run_id, "summary_csv": str(summary_path), "calls_csv": str(calls_path), "written": False}
        _append(calls_path, CALL_COLUMNS, detail_rows)
        _append(summary_path, RUN_COLUMNS, [row])
    return {"run_id": run_id, "summary_csv": str(summary_path), "calls_csv": str(calls_path), "written": True}


def track_run(pipeline):
    """Log completed/failed public entry-point calls; logging failures never change answers."""
    def decorate(function):
        signature = inspect.signature(function)
        @wraps(function)
        def wrapped(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            override = bound.arguments.get("log_usage")
            if override is False:
                return function(*args, **kwargs)
            try:
                config = load_config()
            except Exception as error:
                warnings.warn(f"Usage CSV logging unavailable: {error}", RuntimeWarning)
                return function(*args, **kwargs)
            if override is not True and not config.get("usage_logging", {}).get("enabled", True):
                return function(*args, **kwargs)
            collector = bound.arguments.get("usage_log")
            if collector is None:
                collector = []
                bound.arguments["usage_log"] = collector
            offset = len(collector)
            start = time.perf_counter()
            result, failure = None, None
            try:
                result = function(*bound.args, **bound.kwargs)
                return result
            except Exception as error:
                failure = f"{type(error).__name__}: {error}"
                raise
            finally:
                enabled = bound.arguments.get("decompose")
                if enabled is None:
                    enabled = config.get("supervisor", {}).get("decompose", False)
                payload = result if result is not None else {
                    "question": bound.arguments.get("question", ""), "usage": collector[offset:],
                    "variant": "B_decomposition" if enabled else "A_baseline",
                }
                try:
                    tracking = append_run(payload, pipeline, config=config, error=failure,
                                          elapsed=round(time.perf_counter() - start, 4))
                    if result is not None:
                        result["usage_tracking"] = tracking
                except Exception as error:
                    warnings.warn(f"Usage CSV could not be saved: {error}", RuntimeWarning)
        return wrapped
    return decorate


def import_trace(path, pipeline):
    bundle = json.loads(Path(path).read_text())
    digest = hashlib.sha256(json.dumps(bundle, sort_keys=True).encode()).hexdigest()[:24]
    return append_run(bundle, pipeline, source="trace_import", run_id="trace-" + digest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["import-trace"])
    parser.add_argument("path", type=Path)
    parser.add_argument("--pipeline", choices=["supervisor", "graph"], required=True)
    args = parser.parse_args()
    print(json.dumps(import_trace(args.path, args.pipeline), indent=2))


if __name__ == "__main__":
    main()
