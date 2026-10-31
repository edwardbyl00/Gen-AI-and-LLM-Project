"""Follow-up rewrite (P3): turn a chat follow-up into a standalone question.

Chat mode only. "What about Bishan?" after a Tampines 4-room question
becomes "What did 4-room flats in Bishan sell for recently?", so the
supervisor and agents, which see one question at a time, get the meaning
the user intended. With no earlier turns the graph skips this entirely.

One model call, with the same settings and usage recording as the router.
"""

import json
from datetime import date
from pathlib import Path

from agents.supervisor.router import load_settings, make_client, record_usage

PROMPT_FILE = Path(__file__).parent / "prompts" / "rewrite_v1.md"

# How much of the chat the rewrite sees: enough for "what about ...?",
# without paying for a long chat on every turn. 3 was too few: a couple of
# clarifying exchanges pushed the turn that named the flat type out of view.
MAX_TURNS = 6
MAX_ANSWER_CHARS = 600

REWRITE_SCHEMA = {
    "name": "standalone_question",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {"question": {"type": "string"}},
        "required": ["question"],
        "additionalProperties": False,
    },
}


class RewriteReplyError(Exception):
    """The model replied, but with no usable content (e.g. a refusal)."""


def chat_context(history, message):
    """The last few turns and the new message, as the model sees them."""
    lines = []
    for n, turn in enumerate(history[-MAX_TURNS:], 1):
        lines.append(f"Turn {n}")
        lines.append(f"User: {turn.get('user_question', turn.get('question'))}")
        if turn.get("question") and turn["question"] != turn.get("user_question"):
            lines.append(f"Understood as: {turn['question']}")
        price = turn.get("price_result")
        if price:
            lines.append(f"Price data used: town {price.get('town')}, flat type "
                         f"{price.get('flat_type')}, {price.get('period_start')} to "
                         f"{price.get('period_end')}")
        answer = " ".join(str((turn.get("answer") or {}).get("answer", "")).split())
        if len(answer) > MAX_ANSWER_CHARS:
            answer = answer[:MAX_ANSWER_CHARS] + "..."
        lines.append(f"Assistant: {answer}")
        lines.append("")
    lines.append(f"New message: {message}")
    return "\n".join(lines)


def rewrite_question(message, history, today=None, usage_log=None, client=None):
    """Return the new message as a standalone question."""
    settings = load_settings()
    client = client or make_client(settings.get("timeout_seconds"))
    today = today or date.today().isoformat()
    request = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": PROMPT_FILE.read_text().replace("{today}", today)},
            {"role": "user", "content": chat_context(history, message)},
        ],
        "response_format": {"type": "json_schema", "json_schema": REWRITE_SCHEMA},
    }
    for key, api_key in (("temperature", "temperature"), ("seed", "seed"),
                         ("max_output_tokens", "max_completion_tokens")):
        if settings.get(key) is not None:
            request[api_key] = settings[key]

    response = client.chat.completions.create(**request)
    record_usage(usage_log, "rewrite", response)
    content = response.choices[0].message.content
    if content is None:
        raise RewriteReplyError(
            f"No content in reply (refusal: {getattr(response.choices[0].message, 'refusal', None)})")
    return json.loads(content)["question"].strip() or message
