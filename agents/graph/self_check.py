"""Self check (P3): decide whether a synthesised answer is weak, and where
to send it back.

Two layers, cheapest first:
  1. Code checks (free): agent errors, the fallback answer, citations that
     synthesis had to remove, passages provided but nothing cited.
  2. LLM check (one model call, if enabled in config.yaml): reviews the
     answer against the synthesis rules A1-A8, using exactly the context
     synthesis saw. Only runs when the code checks find nothing.

Each problem names a target: "synthesis", "price_agent", "policy_agent" or
"supervisor". The graph retries the targets it can; "supervisor" is only
recorded for now, because the router takes no feedback and, at
temperature 0, would return the same route again.

This is deliberately separate from P5's AI judge, which grades final
answers in evaluation; reusing it here would let the judge shape the
answers it later grades.
"""

import json
from datetime import date
from pathlib import Path

import yaml

from agents.supervisor.router import CONFIG_FILE, load_settings, make_client, record_usage
from agents.supervisor.synthesis import FALLBACK_ANSWER, build_context

PROMPT_FILE = Path(__file__).parent / "prompts" / "self_check_v1.md"

CHECK_SCHEMA = {
    "name": "self_check",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "weak": {"type": "boolean"},
            "problems": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rule": {"type": "string"},
                        "issue": {"type": "string"},
                        "target": {"type": "string", "enum": ["synthesis", "supervisor"]},
                    },
                    "required": ["rule", "issue", "target"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["weak", "problems"],
        "additionalProperties": False,
    },
}


class SelfCheckReplyError(Exception):
    """The model replied, but with no usable content (e.g. a refusal)."""


def load_self_check_settings():
    """Read the "self_check" section of config.yaml."""
    with open(CONFIG_FILE) as f:
        config = yaml.safe_load(f) or {}
    settings = config.get("self_check", {})
    return {"max_retries": settings.get("max_retries", 1),
            "llm_check": settings.get("llm_check", True)}


def code_checks(state):
    """Free checks on the state. Returns a list of problems."""
    problems = []
    for name, error in (state.get("agent_errors") or {}).items():
        problems.append({"rule": "code", "target": f"{name}_agent",
                         "issue": f"The {name} agent failed ({error})."})

    answer = state.get("answer") or {}
    if answer.get("answer") == FALLBACK_ANSWER:
        problems.append({"rule": "code", "target": "synthesis",
                         "issue": "Synthesis failed and the fallback answer was used."})
        return problems

    for event in answer.get("events", []):
        if event.get("code") == "invalid_citation":
            problems.append({"rule": "A2", "target": "synthesis",
                             "issue": f"Cited a passage that does not exist: {event.get('detail')}."})

    evidence = (state.get("policy_result") or {}).get("evidence") or []
    if evidence and not answer.get("declined") and not answer.get("cited"):
        problems.append({"rule": "A2", "target": "synthesis",
                         "issue": "Policy passages were provided, but the answer cites none of them."})
    return problems


def llm_check(state, usage_log=None, client=None):
    """Review the answer against rules A1-A8. Returns {"weak", "problems"}."""
    settings = load_settings()
    client = client or make_client(settings.get("timeout_seconds"))
    today = state.get("today") or date.today().isoformat()
    context, _ = build_context(state)  # exactly what synthesis saw
    answer = state.get("answer") or {}
    review = (f"{context}\n\n---\nDraft answer:\n{answer.get('answer', '')}\n\n"
              f"Passage numbers cited: {answer.get('cited', [])}")

    request = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": PROMPT_FILE.read_text().replace("{today}", today)},
            {"role": "user", "content": review},
        ],
        "response_format": {"type": "json_schema", "json_schema": CHECK_SCHEMA},
    }
    for key, api_key in (("temperature", "temperature"), ("seed", "seed"),
                         ("max_output_tokens", "max_completion_tokens")):
        if settings.get(key) is not None:
            request[api_key] = settings[key]

    response = client.chat.completions.create(**request)
    record_usage(usage_log, "self_check", response)
    message = response.choices[0].message
    if message.content is None:
        raise SelfCheckReplyError(f"No content in reply (refusal: {getattr(message, 'refusal', None)})")
    return json.loads(message.content)


def feedback_text(problems):
    """Turn the synthesis problems into instructions for the rewrite."""
    issues = [f"- ({p['rule']}) {p['issue']}" for p in problems if p["target"] == "synthesis"]
    if not issues:
        return None
    return ("A reviewer found these problems in your previous draft. Write the answer "
            "again, following all the answer rules, and fix them:\n" + "\n".join(issues))
