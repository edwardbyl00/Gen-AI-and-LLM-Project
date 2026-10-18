"""Supervisor router: turns a user question into a routing record.

Rules: Docs/routing_spec.md
Output fields: Docs/p2_supervisor_contract.md (section A1)
"""

import json
import os
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPT_FILE = Path(__file__).parent / "prompts" / "supervisor_v1.md"
CONFIG_FILE = PROJECT_ROOT / "config.yaml"

# The exact shape the model must reply in. With "strict": True the API
# refuses to return anything that does not match (structured output).
ROUTING_SCHEMA = {
    "name": "routing_record",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "route": {"type": "string", "enum": ["price", "policy", "both", "none"]},
            "false_belief": {"type": "boolean"},
            "answerable": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": ["route", "false_belief", "answerable", "reason"],
        "additionalProperties": False,
    },
}


def load_settings():
    """Read the model settings from config.yaml (never typed into code)."""
    with open(CONFIG_FILE) as f:
        config = yaml.safe_load(f) or {}
    llm = config.get("llm", {})
    if not llm.get("model"):
        raise ValueError("No model set. Add llm.model to config.yaml.")
    return llm


def load_prompt(today):
    """Read the prompt file and put today's date into it."""
    template = PROMPT_FILE.read_text()
    return template.replace("{today}", today)


def make_client():
    """Create the OpenAI client using the key stored in .env."""
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not api_key:
        raise ValueError("No API key found. Add OPENAI_API_KEY to .env.")
    return OpenAI(api_key=api_key)


def route_question(question, client=None, today=None):
    """Classify one question. Returns a dict with route, false_belief,
    answerable and reason."""
    settings = load_settings()
    today = today or date.today().isoformat()
    client = client or make_client()

    request = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": load_prompt(today)},
            {"role": "user", "content": question},
        ],
        "response_format": {"type": "json_schema", "json_schema": ROUTING_SCHEMA},
    }
    # Only send these if config.yaml sets them; some models reject them.
    if settings.get("temperature") is not None:
        request["temperature"] = settings["temperature"]
    if settings.get("seed") is not None:
        request["seed"] = settings["seed"]

    response = client.chat.completions.create(**request)
    return json.loads(response.choices[0].message.content)


if __name__ == "__main__":
    import sys

    question = " ".join(sys.argv[1:]) or (
        "What was the median resale price of a 4-room flat in Tampines in 2024?"
    )
    print(json.dumps(route_question(question), indent=2))
