"""Shared routing and task execution for the sequential supervisor and P3 graph."""

import time

import yaml

from agents.supervisor.checks import valid_tasks
from agents.supervisor.router import CONFIG_FILE

AGENTS_FOR_ROUTE = {
    "price": ("price",), "policy": ("policy",),
    "both": ("price", "policy"), "none": (),
}


def resolve_decompose(value=None):
    if value is None:
        with open(CONFIG_FILE) as stream:
            value = (yaml.safe_load(stream) or {}).get("supervisor", {}).get("decompose", False)
    if not isinstance(value, bool):
        raise ValueError("decompose must be a boolean")
    return value


def route_with_tasks(question, today, usage, route_fn, decompose):
    """Invoke the existing router once (with its existing safety retries)."""
    kwargs = {"today": today, "usage_log": usage}
    if decompose:
        kwargs["decompose"] = True
    routing, events = route_fn(question, **kwargs)
    if decompose and not valid_tasks(routing):
        raise ValueError("Decomposition routing returned invalid tasks")
    return routing, events


def tasks_for_route(question, routing, decompose):
    if decompose:
        return routing["tasks"]
    return [{"id": name, "agent": name, "question": question, "required_elements": []}
            for name in AGENTS_FOR_ROUTE[routing["route"]]]


def execute_task(task, agent, today, usage, *, decompose, attempt=1, strict=False):
    """Run one focused task; both entry points use the same log/error contract."""
    start = time.perf_counter()
    usage_start = len(usage)
    record = {"task": task, "result": None, "error": None}
    step = {"step": task["agent"] + "_agent"}
    try:
        result = agent(task["question"], today, usage_log=usage)
        step["stub"] = bool(result.get("stub"))
        record["result"] = result
    except Exception as error:
        if strict:
            raise
        record["error"] = f"{type(error).__name__}: {error}"
        step["error"] = record["error"]
    finally:
        step["seconds"] = round(time.perf_counter() - start, 2)
        if decompose:
            step.update(task_id=task["id"], attempt=attempt)
            record.update(seconds=step["seconds"], attempt=attempt)
            for index in range(usage_start, len(usage)):
                # Copy so an injected agent reusing a dict cannot retag old calls.
                usage[index] = {**usage[index], "task_id": task["id"], "attempt": attempt}
    return record, step
