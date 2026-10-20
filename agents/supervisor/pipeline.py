"""The supervisor pipeline: route a question, then call the right agents.

Produces a "bundle" holding everything synthesis needs, plus a step log.
Synthesis (the answer itself) is added in the next phase.

Usage (one real routing call; agents follow config.yaml):
    python -m agents.supervisor.pipeline "Can I use CPF for a resale flat?"
"""

import json
import time
from datetime import date

from agents.supervisor.adapters import get_policy_agent, get_price_agent
from agents.supervisor.checks import safe_route

# Tuple order determines execution order and the order of entries in the step log.
AGENTS_FOR_ROUTE = {
    "price": ("price",),
    "policy": ("policy",),
    "both": ("price", "policy"),
    "none": (),
}


def handle_question(question, today=None, route_fn=safe_route,
                    price_fn=None, policy_fn=None, strict=False):
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
    steps = []

    start = time.perf_counter()
    # Routing must succeed before agents can be selected. Routing errors propagate
    # to the caller, even when strict=False.
    routing, events = route_fn(question, today=today)
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

    return {
        "question": question,
        "today": today,
        "routing": routing,
        "price_result": results["price"],
        "policy_result": results["policy"],
        "agent_errors": errors,
        "steps": steps,
    }


def _since(start):
    """Return elapsed seconds from a monotonic timer, rounded for the step log."""
    return round(time.perf_counter() - start, 2)


if __name__ == "__main__":
    import sys

    question = " ".join(sys.argv[1:]) or "Can I use CPF for a resale flat?"
    print(json.dumps(handle_question(question, strict=True), indent=2, default=str))
