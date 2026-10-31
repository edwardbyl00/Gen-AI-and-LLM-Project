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

from agents.supervisor.adapters import get_policy_agent, get_price_agent
from agents.supervisor.checks import safe_route
from agents.supervisor.router import estimate_cost_usd
from agents.supervisor.synthesis import FALLBACK_ANSWER, format_answer, synthesise
from agents.supervisor.tasks import execute_task, resolve_decompose, route_with_tasks, tasks_for_route
from agents.supervisor.usage_log import track_run


@track_run("supervisor")
def handle_question(question, today=None, route_fn=safe_route,
                    price_fn=None, policy_fn=None, synth_fn=None, strict=False,
                    decompose=None, usage_log=None, log_usage=None):
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
    decompose = resolve_decompose(decompose)
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
    routing, events = route_with_tasks(question, today, usage, route_fn, decompose)
    steps.append({"step": "router", "seconds": _since(start),
                  "output": routing, "events": events})

    # Keep a stable bundle shape: skipped or failed agents have a None result.
    # agent_errors distinguishes failures from agents that were never selected.
    results = {"price": None, "policy": None}
    errors = {}
    task_results = []
    for task in tasks_for_route(question, routing, decompose):
        name = task["agent"]
        record, step = execute_task(task, agents[name], today, usage,
                                    decompose=decompose, strict=strict)
        steps.append(step)
        if record["error"]:
            errors[task["id"] if decompose else name] = record["error"]
        elif results[name] is None:
            results[name] = record["result"]
        if decompose:
            task_results.append(record)

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
                            "cited": [], "sources": [], "events": [],
                            "needs_clarification": False, "cannot_answer": []}
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
