"""Synthesis: turn the pipeline's bundle into the final answer.

Rules: Docs/routing_spec.md section 7, written as A1 to A8 in
prompts/synthesis_v1.md.

The model writes the answer text and lists the passage numbers it cited.
The code, not the model, builds the source list (titles, dates, links),
so the answer can never contain an invented link.
"""

import json
from datetime import date
from pathlib import Path

from agents.supervisor.router import load_settings, make_client

PROMPT_FILE = Path(__file__).parent / "prompts" / "synthesis_v1.md"

SYNTHESIS_SCHEMA = {
    "name": "answer",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "cited": {"type": "array", "items": {"type": "integer"}},
            "declined": {"type": "boolean"},
        },
        "required": ["answer", "cited", "declined"],
        "additionalProperties": False,
    },
}

FALLBACK_ANSWER = ("Sorry, I couldn't put together an answer just now. "
                   "Please try again, or check the official HDB and CPF websites.")


class SynthesisReplyError(Exception):
    """The model replied, but with no usable content (e.g. a refusal)."""


def yes_no(value):
    return "yes" if value else "no"


def build_context(bundle):
    """Write everything the model may use into one text block.

    Returns (context_text, passages). Passages are numbered from 1, in the
    same order as the text, so a citation [n] means passages[n - 1].
    """
    routing = bundle["routing"]
    lines = [
        f"Question: {bundle['question']}",
        "",
        "Routing note:",
        f"- sources searched: {routing['route']}",
        f"- possible false belief: {yes_no(routing['false_belief'])}"
        + (" (a suspicion only; check it against the sources)" if routing["false_belief"] else ""),
        f"- answerable: {yes_no(routing['answerable'])}",
    ]

    price = bundle.get("price_result")
    lines += ["", "Price facts (HDB resale transactions):"]
    if price:
        if price.get("stub"):
            lines.append("[STUB DATA: not real prices]")
        for key in ("town", "flat_type", "period_start", "period_end", "median_price",
                    "min_price", "max_price", "n_deals", "data_as_of"):
            lines.append(f"- {key}: {price.get(key)}")
    else:
        lines.append("- none provided")

    policy = bundle.get("policy_result") or {}

    lines += [
        "",
        "Policy agent decision:",
        f"- decision: {policy.get('decision') or 'not stated'}",
        f"- reason: {policy.get('reason') or 'not stated'}",
    ]

    raw_passages = policy.get("evidence", [])

    passages = []
    by_url = {}

    for item in raw_passages:
        url = item.get("url")

        if url and url in by_url:
            existing = by_url[url]
            extra_text = str(item.get("text", "")).strip()

            if extra_text and extra_text not in existing.get("text", ""):
                existing["text"] = (
                    existing.get("text", "").rstrip()
                    + "\n\n"
                    + extra_text
                )
            continue

        merged = dict(item)
        passages.append(merged)

        if url:
            by_url[url] = merged

    lines += ["", "Policy passages:"]
    if not passages:
        lines.append("- none provided")
    for n, item in enumerate(passages, start=1):
        lines.append(f"[{n}] {item.get('title')} | source: {item.get('source')} | "
                     f"effective date: {item.get('effective_date') or 'not stated'}")
        lines.append(str(item.get("text", "")).strip())

    errors = bundle.get("agent_errors") or {}
    if errors:
        lines += ["", "Note: these sources failed and gave no data: " + ", ".join(errors)]

    return "\n".join(lines), passages


def check_citations(cited, passages):
    """Keep only citation numbers that point at a real passage."""
    valid, events = [], []
    for n in cited:
        if 1 <= n <= len(passages) and n not in valid:
            valid.append(n)
        elif not 1 <= n <= len(passages):
            events.append({"code": "invalid_citation",
                           "detail": f"cited [{n}] but only {len(passages)} passages exist"})
    return valid, events


def synthesise(bundle, client=None):
    """Write the answer for one bundle. Returns a dict with the answer,
    the cited sources (built by code) and any events."""
    settings = load_settings()
    client = client or make_client(settings.get("timeout_seconds"))
    today = bundle.get("today") or date.today().isoformat()
    context, passages = build_context(bundle)

    request = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": PROMPT_FILE.read_text().replace("{today}", today)},
            {"role": "user", "content": context},
        ],
        "response_format": {"type": "json_schema", "json_schema": SYNTHESIS_SCHEMA},
    }
    for key, api_key in (("temperature", "temperature"), ("seed", "seed"),
                         ("max_output_tokens", "max_completion_tokens")):
        if settings.get(key) is not None:
            request[api_key] = settings[key]

    message = client.chat.completions.create(**request).choices[0].message
    if message.content is None:
        raise SynthesisReplyError(f"No content in reply (refusal: {getattr(message, 'refusal', None)})")
    reply = json.loads(message.content)

    cited, events = check_citations(reply["cited"], passages)
    sources = [{"n": n,
                "title": passages[n - 1].get("title"),
                "url": passages[n - 1].get("url"),
                "effective_date": passages[n - 1].get("effective_date")}
               for n in cited]
    return {"answer": reply["answer"], "declined": reply["declined"],
            "cited": cited, "sources": sources, "events": events}


def format_answer(result):
    """The answer text followed by the source list, for display."""
    text = result["answer"]
    if result.get("sources"):
        text += "\n\nSources:"
        for s in result["sources"]:
            date_note = f", effective {s['effective_date']}" if s.get("effective_date") else ""
            text += f"\n[{s['n']}] {s['title']}{date_note}: {s['url'] or 'link unavailable'}"
    return text
