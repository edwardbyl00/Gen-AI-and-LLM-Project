"""Approach A: the LLM fills in a fixed set of filters (a "filter tool").

The LLM never sees prices and never calculates anything. It only turns the
user's wording into town, flat type and period. Code does the rest.
"""

import json
from pathlib import Path

from agents.supervisor.router import load_settings, make_client

PROMPT_FILE = Path(__file__).parent / "prompts" / "price_filters_v1.md"


def record_usage(usage_log, step, response):
    """Add one call's token counts to usage_log (a list), if one is given.
    Same format as the router's step log."""
    if usage_log is None:
        return
    usage = getattr(response, "usage", None)
    usage_log.append({
        "step": step,
        "input_tokens": getattr(usage, "prompt_tokens", None),
        "output_tokens": getattr(usage, "completion_tokens", None),
    })


class PriceFilterReplyError(Exception):
    """The model replied, but with no usable content (e.g. a refusal)."""


def filter_schema(towns, flat_types):
    """The exact reply shape. With strict mode the API refuses anything else."""
    month = {"type": ["string", "null"], "pattern": r"^\d{4}-\d{2}$"}
    return {
        "name": "price_filters",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "town": {"type": ["string", "null"], "enum": list(towns) + [None]},
                "flat_type": {"type": ["string", "null"], "enum": list(flat_types) + [None]},
                "period_start": month,
                "period_end": month,
                "last_n_months": {"type": ["integer", "null"]},
                "unmatched_place": {"type": ["string", "null"]},
                "period_words": {"type": ["string", "null"]},
            },
            "required": ["town", "flat_type", "period_start", "period_end",
                         "last_n_months", "unmatched_place", "period_words"],
            "additionalProperties": False,
        },
    }


def build_prompt(today, data_start, data_end, towns, flat_types):
    """Fill the prompt template with today's date, data range and valid values."""
    return (PROMPT_FILE.read_text()
            .replace("{today}", today)
            .replace("{data_start}", data_start)
            .replace("{data_end}", data_end)
            .replace("{towns}", "\n".join(towns))
            .replace("{flat_types}", "\n".join(flat_types)))


def extract_filters(question, query_date, table, client=None, usage_log=None):
    """Ask the LLM for the filters. Returns a dict with the seven fields."""
    settings = load_settings()
    client = client or make_client(settings.get("timeout_seconds"))
    towns = sorted(table["town"].unique())
    flat_types = sorted(table["flat_type"].unique())

    request = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": build_prompt(
                query_date, table["month"].min(), table["month"].max(), towns, flat_types)},
            {"role": "user", "content": question},
        ],
        "response_format": {"type": "json_schema",
                            "json_schema": filter_schema(towns, flat_types)},
    }
    # Same optional settings as the router, read from config.yaml.
    if settings.get("temperature") is not None:
        request["temperature"] = settings["temperature"]
    if settings.get("seed") is not None:
        request["seed"] = settings["seed"]
    if settings.get("max_output_tokens") is not None:
        request["max_completion_tokens"] = settings["max_output_tokens"]

    response = client.chat.completions.create(**request)
    record_usage(usage_log, "price_filters", response)
    message = response.choices[0].message
    if message.content is None:
        raise PriceFilterReplyError(
            f"No content in reply (refusal: {getattr(message, 'refusal', None)})")
    return json.loads(message.content)
