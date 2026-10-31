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

With a checkpointer (chat mode), a rewrite node (agents/graph/rewrite.py)
turns a follow-up into a standalone question before the supervisor sees
it, and a remember node appends the finished turn to history, kept per
thread_id:

    START -> rewrite -> supervisor -> ...
    self_check --pass--> remember -> END

Input:  question, today, optional decompose override

Decomposition is planned once by the shared supervisor router. P3 executes
focused tasks per agent branch and retries failed task IDs without replanning.
Output: routing (route, check_premise, answerable, reason,
        needs_clarification, clarifying_question), routing_events,
        price_result, policy_result, agent_errors, answer (answer, declined,
        cited, sources, events, needs_clarification, cannot_answer),
        self_check (verdict, problems, retry), attempts, steps (step log)
        and usage (token counts); in chat mode also history (one entry
        per turn, so every turn keeps its own analysis)

Usage (real model calls, needs OPENAI_API_KEY in .env; the policy agent
also needs the local vector store in data/vector_db/):
    python -m agents.graph.graph "Can I use CPF for a resale flat?"
    python -m agents.graph.graph --thread test-1 "What about Bishan?"

--thread continues (or starts) that chat, saved in logs/chat/chats.sqlite,
the same file as the chat page (ui/chat_app.py).
"""

import inspect
import json
import operator
import time
from datetime import date
from pathlib import Path
from typing import Annotated, Literal, NotRequired, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Overwrite

from agents.supervisor.adapters import get_policy_agent
from agents.supervisor.checks import safe_route
from agents.supervisor.synthesis import FALLBACK_ANSWER, synthesise
from agents.supervisor.router import estimate_cost_usd
from agents.supervisor.tasks import execute_task, resolve_decompose, route_with_tasks, tasks_for_route
from agents.supervisor.usage_log import track_run
from agents.graph.rewrite import rewrite_question
from agents.graph.self_check import code_checks, feedback_text, llm_check, load_self_check_settings

# Chat memory for --thread and the chat page; logs/chat/ is in .gitignore.
CHAT_DB = Path(__file__).resolve().parents[2] / "logs" / "chat" / "chats.sqlite"


class Routing(TypedDict):
    """The supervisor's record (Docs/supervisor_guide.md)."""
    route: Literal["price", "policy", "both", "none"]  # which agents to call
    check_premise: bool  # question makes a claim synthesis must check against the sources
    answerable: bool     # False means decline, offering related facts as context
    reason: str          # one sentence, cites a rule (R1-R5) where one applies
    needs_clarification: NotRequired[bool]   # too unclear to route; ask the user instead
    clarifying_question: NotRequired[Optional[str]]
    tasks: NotRequired[list]


def merge_dicts(left, right):
    """Reducer: combine updates instead of the last one overwriting the other.
    A value of None removes that key (e.g. an agent that succeeded on retry)."""
    merged = {**(left or {}), **(right or {})}
    return {key: value for key, value in merged.items() if value is not None}


class State(TypedDict, total=False):
    # Input
    question: str
    today: str
    decompose: bool
    variant: str
    task_records: Annotated[dict, merge_dicts]  # latest result per task; parallel-safe
    task_results: list  # ordered snapshot for synthesis and self-check
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
    # Chat mode only: what the user typed, and the finished earlier turns.
    # history is the one field kept from turn to turn; run() resets the rest.
    user_question: str
    history: list


def make_supervisor_node(route_fn=safe_route, decompose=None, failure_usage_log=None):
    """Use the same router and decomposition setting as the sequential pipeline."""
    def supervisor(state):
        enabled = resolve_decompose(state.get("decompose", decompose))
        usage = []
        start = time.perf_counter()
        try:
            routing, events = route_with_tasks(
                state["question"], state["today"], usage, route_fn, enabled)
        except Exception:
            if failure_usage_log is not None:
                failure_usage_log.extend(usage)
            raise
        step = {"step": "router", "seconds": round(time.perf_counter() - start, 2),
                "output": routing, "events": events}
        return {"routing": routing, "routing_events": events, "steps": [step], "usage": usage,
                "decompose": enabled, "variant": "B_decomposition" if enabled else "A_baseline"}
    return supervisor


def make_agent_node(name, agent):
    """Execute this branch's focused tasks, keeping other branches' records."""
    def agent_node(state):
        enabled = state.get("decompose", False)
        all_tasks = [task for task in tasks_for_route(state["question"], state["routing"], enabled)
                     if task["agent"] == name]
        tasks = all_tasks
        if enabled and state.get("attempts", 0):
            # Code checks name failed tasks. Retrying one must not repeat the
            # successful sibling tasks or re-plan the original mixed question.
            targets = {p["task_id"] for p in state.get("self_check", {}).get("problems", [])
                       if p.get("target") == name + "_agent" and p.get("task_id")}
            if targets:
                tasks = [task for task in all_tasks if task["id"] in targets]
        usage, steps, updates, errors = [], [], {}, {}
        latest = dict(state.get("task_records", {}))
        first_result = None
        for task in tasks:
            record, step = execute_task(task, agent, state["today"], usage,
                decompose=enabled, attempt=state.get("attempts", 0) + 1)
            steps.append(step)
            errors[task["id"] if enabled else name] = record["error"]
            if enabled:
                updates[task["id"]] = record
                latest[task["id"]] = record
            elif record["error"] is None:
                first_result = record["result"]
        if enabled:
            first_result = next((latest[t["id"]]["result"] for t in all_tasks
                if t["id"] in latest and latest[t["id"]]["result"] is not None), None)
        result = {name + "_result": first_result, "agent_errors": errors,
                  "steps": steps, "usage": usage}
        if enabled:
            result["task_records"] = updates
        return result
    return agent_node


def make_price_node(price_fn=None):
    if price_fn is None:
        from agents.price import run_price_agent
        price_fn = run_price_agent
    return make_agent_node("price", price_fn)


def make_policy_node(policy_fn=None):
    # Forward usage_log so P5's assessor calls count in graph cost too.
    return make_agent_node("policy", policy_fn or get_policy_agent())


def make_synthesis_node(synth_fn=synthesise):
    """Wrap synthesis as a graph node. synth_fn takes (bundle, usage_log=...);
    the state already has every key the bundle needs (question, today,
    routing, price_result, policy_result, agent_errors)."""
    def synthesis(state):
        task_update = {}
        if state.get("decompose"):
            ordered = [state["task_records"][task["id"]] for task in state["routing"]["tasks"]]
            task_update = {"task_results": ordered}
            state = {**state, **task_update}
        usage = []
        start = time.perf_counter()
        # A synthesis failure gives P2's fallback answer, as in pipeline.py.
        try:
            answer = call_synthesis(synth_fn, state, usage, state.get("feedback"))
        except Exception as error:
            answer = {"answer": FALLBACK_ANSWER, "declined": True,
                      "cited": [], "sources": [], "events": [],
                      "needs_clarification": False, "cannot_answer": []}
            step = {"step": "synthesis", "seconds": round(time.perf_counter() - start, 2),
                    "error": f"{type(error).__name__}: {error}"}
            return {**task_update, "answer": answer, "steps": [step], "usage": usage}
        step = {"step": "synthesis", "seconds": round(time.perf_counter() - start, 2),
                "events": answer.get("events", [])}
        if state.get("feedback"):
            step["feedback"] = state["feedback"]
        return {**task_update, "answer": answer, "steps": [step], "usage": usage}
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


def make_rewrite_node(rewrite_fn=rewrite_question):
    """Chat mode: rewrite a follow-up as a standalone question.

    rewrite_fn(message, history, today, usage_log=...) returns the question.
    The first turn of a chat has no history, so nothing is called or logged.
    If the rewrite fails, the message goes on unchanged."""
    def rewrite(state):
        history = state.get("history") or []
        if not history:
            return {}
        message = state.get("user_question", state["question"])
        usage = []
        start = time.perf_counter()
        step = {"step": "rewrite"}
        try:
            question = rewrite_fn(message, history, state["today"], usage_log=usage)
        except Exception as error:
            question = message
            step["error"] = f"{type(error).__name__}: {error}"
        step.update(seconds=round(time.perf_counter() - start, 2),
                    output=question, changed=question != message)
        return {"question": question, "steps": [step], "usage": usage}
    return rewrite


# What each history entry keeps: enough to show the turn's analysis again.
TURN_KEYS = ("question", "today", "routing", "price_result", "policy_result",
             "task_results", "agent_errors", "answer", "self_check", "attempts", "steps", "usage")


def make_remember_node():
    """Chat mode: append the finished turn to this thread's history."""
    def remember(state):
        turn = {key: state.get(key) for key in TURN_KEYS}
        turn["user_question"] = state.get("user_question", state["question"])
        turn["cost_usd"] = estimate_cost_usd(state.get("usage", []))
        return {"history": (state.get("history") or []) + [turn]}
    return remember


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
                check_fn=llm_check, self_check_settings=None, decompose=None, usage_log=None,
                checkpointer=None, rewrite_fn=rewrite_question):
    """checkpointer (e.g. MemorySaver()) turns on chat mode: state is saved
    per thread_id, a rewrite node makes follow-ups standalone and a remember
    node keeps each turn. Without one, the graph is unchanged: one question
    in, one answer out."""
    def capture(node):
        def wrapped(state):
            update = node(state)
            if usage_log is not None:
                usage_log.extend(update.get("usage", []))
            return update
        return wrapped

    graph = StateGraph(State)
    graph.add_node("supervisor", capture(make_supervisor_node(route_fn, decompose, usage_log)))
    graph.add_node("price_agent", capture(make_price_node(price_fn)))
    graph.add_node("policy_agent", capture(make_policy_node(policy_fn)))
    graph.add_node("synthesis", capture(make_synthesis_node(synth_fn)))
    graph.add_node("self_check", capture(make_self_check_node(check_fn, self_check_settings)))

    if checkpointer is None:
        graph.add_edge(START, "supervisor")
    else:
        graph.add_node("rewrite", capture(make_rewrite_node(rewrite_fn)))
        graph.add_edge(START, "rewrite")
        graph.add_edge("rewrite", "supervisor")
    graph.add_conditional_edges("supervisor", route_after_supervisor,
                                ["price_agent", "policy_agent", "synthesis"])
    # For route both, the agents run in the same step, so synthesis runs once, after both.
    graph.add_edge("price_agent", "synthesis")
    graph.add_edge("policy_agent", "synthesis")
    graph.add_edge("synthesis", "self_check")
    if checkpointer is None:
        graph.add_conditional_edges("self_check", route_after_self_check,
                                    ["synthesis", "price_agent", "policy_agent", END])
        return graph.compile()
    graph.add_node("remember", make_remember_node())
    graph.add_conditional_edges("self_check", route_after_self_check,
                                {"synthesis": "synthesis", "price_agent": "price_agent",
                                 "policy_agent": "policy_agent", END: "remember"})
    graph.add_edge("remember", END)
    return graph.compile(checkpointer=checkpointer)


def chat_memory(path=CHAT_DB):
    """A SQLite checkpointer for chat mode: every thread saved in one file.

    check_same_thread=False because Streamlit runs each rerun on a different thread."""
    import sqlite3
    from langgraph.checkpoint.sqlite import SqliteSaver

    path.parent.mkdir(parents=True, exist_ok=True)
    saver = SqliteSaver(sqlite3.connect(path, check_same_thread=False))
    saver.setup()  # create the tables now, so a new file can list its (no) chats
    return saver


@track_run("graph")
def run(question, today=None, app=None, decompose=None, usage_log=None, log_usage=None,
        thread_id=None):
    """Run P3 with optional per-request decomposition and external usage capture.

    thread_id (needs an app built with a checkpointer) continues that chat:
    history carries over, every per-turn field starts fresh."""
    start = time.perf_counter()
    supplied_app = app is not None
    app = app or build_graph(usage_log=usage_log)
    initial = {"question": question, "today": today or date.today().isoformat(),
               "price_result": None, "policy_result": None, "agent_errors": {},
               "task_records": {}, "attempts": 0, "feedback": None,
               "steps": [], "usage": []}
    if decompose is not None:
        initial["decompose"] = resolve_decompose(decompose)
    config = None
    if thread_id is not None:
        if not getattr(app, "checkpointer", None):
            raise ValueError("thread_id needs an app built with build_graph(checkpointer=...)")
        # The saved state would otherwise leak into this turn: the reducers
        # would add this turn's steps, usage and errors to the last turn's.
        initial = {**initial, "user_question": question, "task_results": None,
                   "decompose": resolve_decompose(decompose),
                   "steps": Overwrite([]), "usage": Overwrite([]),
                   "agent_errors": Overwrite({}), "task_records": Overwrite({})}
        config = {"configurable": {"thread_id": thread_id}}
    result = app.invoke(initial, config)
    if supplied_app and usage_log is not None:
        usage_log.extend(result["usage"])
    result["cost_usd"] = estimate_cost_usd(result["usage"])
    result["seconds"] = round(time.perf_counter() - start, 4)
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ask the agent graph a question.")
    parser.add_argument("question", nargs="*")
    parser.add_argument("--thread", help="continue (or start) this chat, kept in "
                                         "logs/chat/chats.sqlite")
    args = parser.parse_args()
    question = " ".join(args.question) or "Can I use CPF for a resale flat?"
    if args.thread:
        state = run(question, app=build_graph(checkpointer=chat_memory()), thread_id=args.thread)
    else:
        state = run(question)
    print(json.dumps(state, indent=2))
