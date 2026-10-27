"""The supervisor pipeline as a LangGraph graph (P3).

Built one node at a time. The supervisor node wraps P2's safe_route()
(agents/supervisor/checks.py); its route picks the next node. The policy
node wraps P2's policy adapter (agents/supervisor/adapters.py), which calls
P5's agent. The price node calls P1's run_price_agent() (agents/price/).
The synthesis node wraps P2's synthesise() (agents/supervisor/synthesis.py).
The self check (agents/graph/self_check.py) sends a weak answer back once:

    START -> supervisor --price--> price_agent  --> synthesis -> self_check -> END
                        --policy-> policy_agent --> synthesis
                        --both---> both in parallel, then synthesis once
                        --none---> synthesis (declines)
    self_check --weak--> synthesis (with feedback) or the failed agent(s)

Input:  question, today
Output: routing (route, check_premise, answerable, reason), routing_events,
        price_result, policy_result, agent_errors, answer (answer, declined,
        cited, sources, events), self_check (verdict, problems, retry),
        attempts, steps (step log) and usage (token counts)

Usage (real model calls, needs OPENAI_API_KEY in .env; the policy agent
also needs the local vector store in data/vector_db/):
    python -m agents.graph.graph "Can I use CPF for a resale flat?"
"""

import inspect
import json
import operator
import time
from datetime import date
from typing import Annotated, Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.supervisor.adapters import get_policy_agent
from agents.supervisor.checks import safe_route
from agents.supervisor.synthesis import FALLBACK_ANSWER, synthesise
from agents.graph.self_check import code_checks, feedback_text, llm_check, load_self_check_settings


class Routing(TypedDict):
    """The supervisor's record (Docs/p2_supervisor_code.md)."""
    route: Literal["price", "policy", "both", "none"]  # which agents to call
    check_premise: bool  # question makes a claim synthesis must check against the sources
    answerable: bool     # False means decline, offering related facts as context
    reason: str          # one sentence, cites a rule (R1-R5) where one applies


def merge_dicts(left, right):
    """Reducer: combine updates instead of the last one overwriting the other.
    A value of None removes that key (e.g. an agent that succeeded on retry)."""
    merged = {**(left or {}), **(right or {})}
    return {key: value for key, value in merged.items() if value is not None}


class State(TypedDict, total=False):
    # Input
    question: str
    today: str
    # Supervisor output
    routing: Routing
    routing_events: list  # malformed_output retries and invalid_combo fixes
    # Agent output: None means the agent was not selected or failed
    price_result: Optional[dict]
    policy_result: Optional[dict]
    # Agent failures by agent name; merged, since agents can run in parallel
    agent_errors: Annotated[dict, merge_dicts]
    # Synthesis output: the final answer and its sources (built by code)
    answer: dict
    # Self check: verdict, problems found and what was sent back
    self_check: dict
    attempts: int              # retries used so far
    feedback: Optional[str]    # instructions for the next synthesis, if retried
    # Lists that every node appends to rather than overwrites.
    steps: Annotated[list, operator.add]
    usage: Annotated[list, operator.add]


def make_supervisor_node(route_fn=safe_route):
    """Wrap the router as a graph node. route_fn can be swapped for a fake in tests."""
    def supervisor(state):
        usage = []
        start = time.perf_counter()
        # Routing errors propagate, as in pipeline.py: nothing can run without a route.
        routing, events = route_fn(state["question"], today=state["today"], usage_log=usage)
        step = {"step": "router", "seconds": round(time.perf_counter() - start, 2),
                "output": routing, "events": events}
        return {"routing": routing, "routing_events": events, "steps": [step], "usage": usage}
    return supervisor


def make_price_node(price_fn=None):
    """Wrap the price agent as a graph node. price_fn takes (question, today,
    usage_log=...); by default it is P1's run_price_agent(), which picks
    approach A or B from config.yaml. Called directly rather than through P2's
    adapter, which passes the call through unchanged but drops usage_log."""
    if price_fn is None:
        # Imported here so the graph can be built without loading the price data.
        from agents.price import run_price_agent
        price_fn = run_price_agent

    def price_agent(state):
        usage = []
        start = time.perf_counter()
        # Agent errors are recorded and the run carries on, as in pipeline.py.
        # No matching deals is not an error: the agent returns n_deals 0 and a note.
        try:
            result = price_fn(state["question"], state["today"], usage_log=usage)
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            step = {"step": "price_agent", "seconds": round(time.perf_counter() - start, 2),
                    "error": message}
            return {"price_result": None, "agent_errors": {"price": message},
                    "steps": [step], "usage": usage}
        step = {"step": "price_agent", "seconds": round(time.perf_counter() - start, 2),
                "stub": bool(result.get("stub"))}
        # None clears any error left by an earlier, failed attempt.
        return {"price_result": result, "agent_errors": {"price": None},
                "steps": [step], "usage": usage}
    return price_agent


def make_policy_node(policy_fn=None):
    """Wrap the policy agent as a graph node. policy_fn takes (question, today);
    by default it is P2's adapter, which reads agents.policy (real or stub) and
    policy_top_k from config.yaml."""
    policy_fn = policy_fn or get_policy_agent()

    def policy_agent(state):
        start = time.perf_counter()
        # Agent errors are recorded and the run carries on, as in pipeline.py.
        try:
            result = policy_fn(state["question"], state["today"])
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            step = {"step": "policy_agent", "seconds": round(time.perf_counter() - start, 2),
                    "error": message}
            return {"policy_result": None, "agent_errors": {"policy": message}, "steps": [step]}
        # Token usage is not logged yet: P2's adapter drops P5's assessor_usage.
        step = {"step": "policy_agent", "seconds": round(time.perf_counter() - start, 2),
                "stub": bool(result.get("stub"))}
        # None clears any error left by an earlier, failed attempt.
        return {"policy_result": result, "agent_errors": {"policy": None}, "steps": [step]}
    return policy_agent


def make_synthesis_node(synth_fn=synthesise):
    """Wrap synthesis as a graph node. synth_fn takes (bundle, usage_log=...);
    the state already has every key the bundle needs (question, today,
    routing, price_result, policy_result, agent_errors)."""
    def synthesis(state):
        usage = []
        start = time.perf_counter()
        # A synthesis failure gives P2's fallback answer, as in pipeline.py.
        try:
            answer = call_synthesis(synth_fn, state, usage, state.get("feedback"))
        except Exception as error:
            answer = {"answer": FALLBACK_ANSWER, "declined": True,
                      "cited": [], "sources": [], "events": []}
            step = {"step": "synthesis", "seconds": round(time.perf_counter() - start, 2),
                    "error": f"{type(error).__name__}: {error}"}
            return {"answer": answer, "steps": [step], "usage": usage}
        step = {"step": "synthesis", "seconds": round(time.perf_counter() - start, 2),
                "events": answer.get("events", [])}
        if state.get("feedback"):
            step["feedback"] = state["feedback"]
        return {"answer": answer, "steps": [step], "usage": usage}
    return synthesis


def call_synthesis(synth_fn, state, usage, feedback):
    """Call synthesis, passing self check feedback on a retry.

    If synth_fn accepts a feedback argument it gets it directly. P2's
    synthesise() does not yet, so until it does the feedback is appended to
    the question that synthesis shows the model."""
    if not feedback:
        return synth_fn(state, usage_log=usage)
    try:
        accepts_feedback = "feedback" in inspect.signature(synth_fn).parameters
    except (TypeError, ValueError):
        accepts_feedback = False
    if accepts_feedback:
        return synth_fn(state, usage_log=usage, feedback=feedback)
    return synth_fn({**state, "question": f"{state['question']}\n\n{feedback}"}, usage_log=usage)


AGENT_TARGETS = ("price_agent", "policy_agent")


def make_self_check_node(check_fn=llm_check, settings=None):
    """Judge the answer and decide what, if anything, to send back.

    check_fn(state, usage_log=...) is the LLM review; settings has
    max_retries and llm_check (default: the self_check section of config.yaml)."""
    settings = settings or load_self_check_settings()

    def self_check(state):
        usage = []
        start = time.perf_counter()
        problems = code_checks(state)
        llm_error = None
        # The LLM review only runs when the free checks pass.
        if not problems and settings["llm_check"]:
            try:
                review = check_fn(state, usage_log=usage)
                problems = review["problems"] if review.get("weak") else []
            except Exception as error:
                # A failed review must not block the answer: treat it as a pass, but log it.
                llm_error = f"{type(error).__name__}: {error}"

        # Failed agents are retried first (synthesis then reruns after them);
        # otherwise a writing problem sends the answer back to synthesis.
        # "supervisor" problems are recorded but not retried yet.
        targets = [p["target"] for p in problems]
        retry = [t for t in AGENT_TARGETS if t in targets] or \
                (["synthesis"] if "synthesis" in targets else [])
        attempts = state.get("attempts", 0)
        if attempts >= settings["max_retries"]:
            retry = []

        verdict = {"verdict": "weak" if problems else "pass",
                   "problems": problems, "retry": retry}
        step = {"step": "self_check", "seconds": round(time.perf_counter() - start, 2),
                **verdict}
        if llm_error:
            step["error"] = llm_error
        return {"self_check": verdict,
                "attempts": attempts + 1 if retry else attempts,
                "feedback": feedback_text(problems) if retry == ["synthesis"] else None,
                "steps": [step], "usage": usage}
    return self_check


def route_after_self_check(state):
    """Conditional edge: send the answer back, or finish."""
    return state["self_check"]["retry"] or [END]


ROUTE_TO_NODES = {
    "price": ["price_agent"],
    "policy": ["policy_agent"],
    "both": ["price_agent", "policy_agent"],  # run in parallel
    "none": ["synthesis"],                    # nothing to look up; synthesis declines
}


def route_after_supervisor(state):
    """Conditional edge: pick the next node(s) from the supervisor's route."""
    return ROUTE_TO_NODES[state["routing"]["route"]]


def build_graph(route_fn=safe_route, price_fn=None, policy_fn=None, synth_fn=synthesise,
                check_fn=llm_check, self_check_settings=None):
    graph = StateGraph(State)
    graph.add_node("supervisor", make_supervisor_node(route_fn))
    graph.add_node("price_agent", make_price_node(price_fn))
    graph.add_node("policy_agent", make_policy_node(policy_fn))
    graph.add_node("synthesis", make_synthesis_node(synth_fn))
    graph.add_node("self_check", make_self_check_node(check_fn, self_check_settings))

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", route_after_supervisor,
                                ["price_agent", "policy_agent", "synthesis"])
    # For route both, the agents run in the same step, so synthesis runs once, after both.
    graph.add_edge("price_agent", "synthesis")
    graph.add_edge("policy_agent", "synthesis")
    graph.add_edge("synthesis", "self_check")
    graph.add_conditional_edges("self_check", route_after_self_check,
                                ["synthesis", "price_agent", "policy_agent", END])
    return graph.compile()


def run(question, today=None, app=None):
    """Run one question through the graph and return the final state."""
    app = app or build_graph()
    return app.invoke({"question": question,
                       "today": today or date.today().isoformat(),
                       "price_result": None, "policy_result": None, "agent_errors": {},
                       "attempts": 0, "feedback": None,
                       "steps": [], "usage": []})


if __name__ == "__main__":
    import sys

    question = " ".join(sys.argv[1:]) or "Can I use CPF for a resale flat?"
    state = run(question)
    print(json.dumps(state, indent=2))
