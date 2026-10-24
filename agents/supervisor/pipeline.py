"""The supervisor pipeline: route a question, call the right agents, then
write the answer.

Produces a "bundle" holding the routing record, the agents' results, the
final answer and a step log.

Usage (two real model calls, routing and synthesis; agents follow config.yaml):
    python -m agents.supervisor.pipeline "Can I use CPF for a resale flat?"
"""

import json
import time
from datetime import date

from agents.supervisor.adapters import get_policy_agent, get_price_agent
from agents.supervisor.checks import safe_route
from agents.supervisor.synthesis import FALLBACK_ANSWER, format_answer, synthesise

# Tuple order determines execution order and the order of entries in the step log.
AGENTS_FOR_ROUTE = {
    "price": ("price",),
    "policy": ("policy",),
    "both": ("price", "policy"),
    "none": (),
}


def handle_question(question, today=None, route_fn=safe_route,
                    price_fn=None, policy_fn=None, synth_fn=None, strict=False):
    """Route one question and gather what synthesis needs.

    Optional callables let tests or callers replace routing and agent execution.
    The supplied date (or the local date by default) is shared by all stages.
    strict=True re-raises agent errors (useful while developing);
    otherwise an agent error is recorded and the pipeline carries on.
    """
    today = today or date.today().isoformat()
    agents = {
        "price": price_fn or get_price_agent(),
        "policy": policy_fn or get_policy_agent(),
    }
    usage = []  # token counts, one entry per model call (for cost)
    synth_fn = synth_fn or (lambda b: synthesise(b, usage_log=usage))
    steps = []

    start = time.perf_counter()
    # Routing must succeed before agents can be selected. Routing errors propagate
    # to the caller, even when strict=False.
    routing, events = route_fn(question, today=today, usage_log=usage)
    steps.append({"step": "router", "seconds": _since(start),
                  "output": routing, "events": events})

    # Keep a stable bundle shape: skipped or failed agents have a None result.
    # agent_errors distinguishes failures from agents that were never selected.
    results = {"price": None, "policy": None}
    errors = {}
    for name in AGENTS_FOR_ROUTE[routing["route"]]:
        start = time.perf_counter()
        try:
            results[name] = agents[name](question, today)
            steps.append({"step": f"{name}_agent", "seconds": _since(start),
                          "stub": bool(results[name].get("stub"))})
        except Exception as error:
            if strict:
                raise
            # Preserve the failure and continue to any remaining selected agent.
            errors[name] = f"{type(error).__name__}: {error}"
            steps.append({"step": f"{name}_agent", "seconds": _since(start),
                          "error": errors[name]})

    bundle = {
        "question": question,
        "today": today,
        "routing": routing,
        "price_result": results["price"],
        "policy_result": results["policy"],
        "agent_errors": errors,
        "steps": steps,
        "usage": usage,
    }

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
