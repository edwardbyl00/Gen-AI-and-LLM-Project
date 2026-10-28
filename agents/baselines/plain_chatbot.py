"""Baseline 1 (P1): plain chatbot.

The same LLM and settings as the full system (config.yaml), but no router,
no price data and no policy passages. It answers from its own memory, which
shows what the agents and retrieval add.

chatbot_answer() returns a bundle in the same shape as
agents.supervisor.pipeline.handle_question(), so the team's scoring scripts
can grade it exactly like the full system.
"""

import json
import time
from datetime import date
from pathlib import Path

from agents.supervisor.router import load_settings, make_client

PROMPT_FILE = Path(__file__).parent / "prompts" / "plain_chatbot_v1.md"
ROUTE_LABEL = "baseline_chatbot"

ANSWER_SCHEMA = {
    "name": "chatbot_answer",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "declined": {"type": "boolean"},
        },
        "required": ["answer", "declined"],
        "additionalProperties": False,
    },
}

PRICE_SCHEMA = {
    "name": "chatbot_price_estimate",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "median_price": {"type": ["integer", "null"]},
            "mean_price": {"type": ["integer", "null"]},
            "min_price": {"type": ["integer", "null"]},
            "max_price": {"type": ["integer", "null"]},
            "n_deals": {"type": ["integer", "null"]},
            "declined": {"type": "boolean"},
        },
        "required": ["median_price", "mean_price", "min_price", "max_price",
                     "n_deals", "declined"],
        "additionalProperties": False,
    },
}

PRICE_PROMPT = (
    "You are a helpful assistant. Today's date is {today}. The user asks about HDB "
    "resale prices in Singapore. From your own knowledge, give your best estimate of "
    "the typical (median), average, lowest and highest resale price, and the number of resale deals, "
    "for what they ask. Use null for any figure you cannot estimate, and set declined "
    "to true if you cannot estimate any of them. Reply with JSON only."
)


class ChatbotReplyError(Exception):
    """The model replied, but with no usable content (e.g. a refusal)."""


def _ask(client, settings, system, question, schema, usage_log, step):
    """One structured LLM call with the shared settings from config.yaml."""
    request = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ],
        "response_format": {"type": "json_schema", "json_schema": schema},
    }
    for key, api_key in (("temperature", "temperature"), ("seed", "seed"),
                         ("max_output_tokens", "max_completion_tokens")):
        if settings.get(key) is not None:
            request[api_key] = settings[key]

    response = client.chat.completions.create(**request)
    if usage_log is not None:
        usage = getattr(response, "usage", None)
        usage_log.append({
            "step": step,
            "input_tokens": getattr(usage, "prompt_tokens", None),
            "output_tokens": getattr(usage, "completion_tokens", None),
        })
    message = response.choices[0].message
    if message.content is None:
        raise ChatbotReplyError(
            f"No content in reply (refusal: {getattr(message, 'refusal', None)})")
    return json.loads(message.content)


def chatbot_answer(question, today=None, client=None):
    """Answer one question with the plain chatbot. Returns a pipeline-shaped bundle."""
    settings = load_settings()
    today = today or date.today().isoformat()
    client = client or make_client(settings.get("timeout_seconds"))
    usage = []

    start = time.perf_counter()
    reply = _ask(client, settings, PROMPT_FILE.read_text().replace("{today}", today),
                 question, ANSWER_SCHEMA, usage, "chatbot")
    seconds = round(time.perf_counter() - start, 2)

    return {
        "question": question,
        "today": today,
        "routing": {"route": ROUTE_LABEL, "check_premise": None, "answerable": None,
                    "reason": "No routing: plain chatbot baseline."},
        "price_result": None,
        "policy_result": None,
        "agent_errors": {},
        "steps": [{"step": "chatbot", "seconds": seconds}],
        "usage": usage,
        "answer": {"answer": reply["answer"], "declined": reply["declined"],
                   "cited": [], "sources": [], "events": []},
    }


def chatbot_price_estimate(question, today=None, client=None, usage_log=None):
    """Ask the plain chatbot for price figures only, so its price accuracy can be
    scored against the price table the same way as the price agent's."""
    settings = load_settings()
    today = today or date.today().isoformat()
    client = client or make_client(settings.get("timeout_seconds"))
    return _ask(client, settings, PRICE_PROMPT.replace("{today}", today),
                question, PRICE_SCHEMA, usage_log, "chatbot_price")


# Try the chatbot when this file is run directly.
if __name__ == "__main__":
    import sys

    question = " ".join(sys.argv[1:]) or "What is the Minimum Occupation Period for a resale flat?"
    print(chatbot_answer(question)["answer"]["answer"])
