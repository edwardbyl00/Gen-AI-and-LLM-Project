"""The supervisor pipeline: route a question, call the right agents, then
write the answer.

Produces a "bundle" holding the routing record, the agents' results, the
final answer and a step log.

Usage (routing, synthesis and selected agents make model calls as configured):
    python -m agents.supervisor.pipeline "Can I use CPF for a resale flat?"
"""

import json
import time
from datetime import date

import yaml

from agents.supervisor.adapters import get_policy_agent, get_price_agent
from agents.supervisor.checks import safe_route, valid_tasks
from agents.supervisor.router import CONFIG_FILE, estimate_cost_usd
from agents.supervisor.synthesis import FALLBACK_ANSWER, format_answer, synthesise

# Tuple order determines execution order and the order of entries in the step log.
AGENTS_FOR_ROUTE = {
    "price": ("price",),
    "policy": ("policy",),
    "both": ("price", "policy"),
    "none": (),
}


def handle_question(question, today=None, route_fn=safe_route,
                    price_fn=None, policy_fn=None, synth_fn=None, strict=False,
                    decompose=None, usage_log=None):
    """Route one question and gather what synthesis needs.

    Optional callables let tests or callers replace routing and agent execution.
    The supplied date (or the local date by default) is shared by all stages.
    strict=True re-raises agent errors (useful while developing);
    otherwise an agent error is recorded and the pipeline carries on.
    decompose overrides supervisor.decompose in config.yaml. An optional empty
    usage_log collector retains reported usage even if the pipeline raises.
    """
    today = today or date.today().isoformat()
    pipeline_start = time.perf_counter()
    if decompose is None:
        with open(CONFIG_FILE) as f:
            decompose = (yaml.safe_load(f) or {}).get("supervisor", {}).get("decompose", False)
    if not isinstance(decompose, bool):
        raise ValueError("decompose must be a boolean")
    agents = {
        "price": price_fn or get_price_agent(),
        "policy": policy_fn or get_policy_agent(),
    }
    # External collector preserves reported usage even if routing raises.
    usage = usage_log if usage_log is not None else []
    synth_fn = synth_fn or (lambda b: synthesise(b, usage_log=usage))
    steps = []

    start = time.perf_counter()
    # Routing must succeed before agents can be selected. Routing errors propagate
    # to the caller, even when strict=False.
    route_kwargs = {"today": today, "usage_log": usage}
    if decompose:
        route_kwargs["decompose"] = True
    routing, events = route_fn(question, **route_kwargs)
    if decompose and not valid_tasks(routing):
        raise ValueError("Decomposition routing returned invalid tasks")
    steps.append({"step": "router", "seconds": _since(start),
                  "output": routing, "events": events})

    # Keep a stable bundle shape: skipped or failed agents have a None result.
    # agent_errors distinguishes failures from agents that were never selected.
    results = {"price": None, "policy": None}
    errors = {}
    task_results = []
    tasks = routing["tasks"] if decompose else [
        {"id": name, "agent": name, "question": question, "required_elements": []}
        for name in AGENTS_FOR_ROUTE[routing["route"]]
    ]
    for task in tasks:
        name = task["agent"]
        error_key = task["id"] if decompose else name
        start = time.perf_counter()
        usage_start = len(usage)
        task_record = {"task": task, "result": None, "error": None}
        try:
            result = agents[name](task["question"], today, usage_log=usage)
            task_record["result"] = result
            # Retain legacy fields for callers; synthesis uses all task results.
            if results[name] is None:
                results[name] = result
            steps.append({"step": f"{name}_agent", "seconds": _since(start),
                          "stub": bool(result.get("stub"))})
        except Exception as error:
            if strict:
                raise
            # Preserve the failure and continue to any remaining selected agent.
            errors[error_key] = f"{type(error).__name__}: {error}"
            task_record["error"] = errors[error_key]
            steps.append({"step": f"{name}_agent", "seconds": _since(start),
                          "error": errors[error_key]})
        if decompose:
            steps[-1]["task_id"] = task["id"]
            for entry in usage[usage_start:]:
                entry["task_id"] = task["id"]
            task_record["seconds"] = _since(start)
            task_results.append(task_record)

    bundle = {
        "question": question,
        "today": today,
        "routing": routing,
        "price_result": results["price"],
        "policy_result": results["policy"],
        "agent_errors": errors,
        "steps": steps,
        "usage": usage,
        "variant": "B_decomposition" if decompose else "A_baseline",
    }
    if decompose:
        bundle["task_results"] = task_results

    start = time.perf_counter()
    try:
        bundle["answer"] = synth_fn(bundle)
        steps.append({"step": "synthesis", "seconds": _since(start),
                      "events": bundle["answer"].get("events", [])})
    except Exception as error:
        if strict:
            raise
        bundle["answer"] = {"answer": FALLBACK_ANSWER, "declined": True,
                            "cited": [], "sources": [], "events": []}
        steps.append({"step": "synthesis", "seconds": _since(start),
                      "error": f"{type(error).__name__}: {error}"})
    # Computed last: usage keeps growing until synthesis finishes above.
    bundle["cost_usd"] = estimate_cost_usd(usage)
    bundle["seconds"] = round(time.perf_counter() - pipeline_start, 4)
    return bundle


def _since(start):
    """Return elapsed seconds from a monotonic timer, rounded for the step log."""
    return round(time.perf_counter() - start, 2)


if __name__ == "__main__":
    import sys

    question = " ".join(sys.argv[1:]) or "Can I use CPF for a resale flat?"
    bundle = handle_question(question, strict=True)
    print("\n" + format_answer(bundle["answer"]) + "\n")
    print("Routing:", json.dumps(bundle["routing"]))
    for step in bundle["steps"]:
        extra = " (stub)" if step.get("stub") else ""
        print(f"- {step['step']}: {step['seconds']}s{extra}")
