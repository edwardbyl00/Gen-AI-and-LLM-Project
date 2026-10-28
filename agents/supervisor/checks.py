"""Safety checks on the router's output.

- fix known contradictions (invalid combinations),
- retry once if the reply cannot be read, then use the safest fallback,
- report every fix as an event, so evaluation can count them.

Code walkthrough: Docs/p2_supervisor_code.md
"""

import json

import openai

from agents.supervisor.router import RouterReplyError, route_question

ALLOWED_ROUTES = {"price", "policy", "both", "none"}
REQUIRED_FIELDS = ("route", "check_premise", "answerable", "reason")

SAFE_FALLBACK = {
    "route": "none",
    "check_premise": False,
    "answerable": False,
    "reason": "Router output could not be read; using the safest fallback.",
}

# Failures that mean "this attempt went wrong, try again":
# a bad reply, or a temporary problem on OpenAI's side.
RETRYABLE_ERRORS = (
    json.JSONDecodeError,        # reply was not valid JSON
    RouterReplyError,            # reply had no content (e.g. a refusal)
    openai.APIConnectionError,   # network problem or timeout
    openai.RateLimitError,       # too many requests at once (429)
    openai.InternalServerError,  # OpenAI server error (5xx)
)
# Everything else is a setup bug and is allowed to stop the program, so it
# gets noticed instead of hidden behind the fallback. That includes a wrong
# API key (401), a wrong model name (404), an unsupported setting such as
# temperature (400), and a missing model in config.yaml.


def is_well_formed(record):
    """True if the record has all four fields with allowed values."""
    return (
        isinstance(record, dict)
        and all(field in record for field in REQUIRED_FIELDS)
        and record["route"] in ALLOWED_ROUTES
        and isinstance(record["check_premise"], bool)
        and isinstance(record["answerable"], bool)
        and isinstance(record["reason"], str)
        and record["reason"].strip() != ""
    )


def fix_combinations(record):
    """Apply the invalid combination rules. Returns (fixed_record, fixes)."""
    fixed = dict(record)
    fixes = []

    # Checked first: a premise to check needs evidence, so it gets a lookup.
    if fixed["route"] == "none" and fixed["check_premise"]:
        fixed["route"] = "policy"
        fixes.append("route none with check_premise true: route set to policy")

    # Nothing looked up means nothing to answer from.
    if fixed["route"] == "none" and fixed["answerable"]:
        fixed["answerable"] = False
        fixes.append("route none with answerable true: answerable set to false")

    return fixed, fixes


def valid_tasks(record):
    """Validate execution structure; semantic fidelity is evaluated separately."""
    tasks = record.get("tasks")
    if not isinstance(tasks, list) or len(tasks) > 6:
        return False
    ids = set()
    agents = set()
    for task in tasks:
        if not isinstance(task, dict):
            return False
        if any(not isinstance(task.get(k), str) or not task[k].strip()
               for k in ("id", "agent", "question")):
            return False
        if task["id"] in ids or task["agent"] not in {"price", "policy"}:
            return False
        elements = task.get("required_elements")
        if not isinstance(elements, list) or not elements or any(
                not isinstance(e, str) or not e.strip() for e in elements):
            return False
        ids.add(task["id"])
        agents.add(task["agent"])
    return agents == {"none": set(), "price": {"price"}, "policy": {"policy"},
                      "both": {"price", "policy"}}.get(record.get("route"))


def safe_route(question, router=route_question, **router_kwargs):
    """Route a question with all safety checks applied.

    Returns (record, events). The record always has the four contract
    fields; events list every fix or retry, for the step log.
    """
    events = []

    for attempt in (1, 2):
        try:
            record = router(question, **router_kwargs)
        except RETRYABLE_ERRORS as error:
            events.append({"code": "malformed_output", "attempt": attempt,
                           "detail": f"{type(error).__name__}: {error}"})
            continue

        if not is_well_formed(record):
            events.append({"code": "malformed_output", "attempt": attempt,
                           "detail": f"unusable record: {record!r}"})
            continue

        fixed, fixes = fix_combinations(record)
        if router_kwargs.get("decompose") and not valid_tasks(fixed):
            events.append({"code": "malformed_tasks", "attempt": attempt,
                           "detail": "Tasks invalid or inconsistent with route"})
            continue
        for fix in fixes:
            events.append({"code": "invalid_combo", "attempt": attempt, "detail": fix})
        return fixed, events

    fallback = dict(SAFE_FALLBACK)
    if router_kwargs.get("decompose"):
        fallback["tasks"] = []
    return fallback, events
