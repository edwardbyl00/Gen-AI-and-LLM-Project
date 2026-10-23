import json
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import OpenAI


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
CONFIG_PATH = ROOT / "config.yaml"

load_dotenv(ENV_PATH)


def _load_model():
    with CONFIG_PATH.open(
        "r",
        encoding="utf-8",
    ) as f:
        config = yaml.safe_load(f) or {}

    return config["llm"]["model"]


MODEL = _load_model()


def _get_client():
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY was not found in .env"
        )

    return OpenAI(api_key=api_key)


def assess_evidence(question, evidence):
    """
    Determine which retrieved passages directly help answer
    the question and whether the available evidence is sufficient.

    Returns:
        {
            "sufficient": bool,
            "relevant_indices": [1, 3, ...],
            "reason": str
        }
    """

    passages = []

    for i, item in enumerate(evidence, start=1):
        passages.append(
            f"""
Passage {i}
Title: {item.get("title")}
Source: {item.get("source")}
Text:
{item.get("text")}
""".strip()
        )

    prompt = f"""
Question:
{question}

Candidate policy passages:
{chr(10).join(passages)}

Assess the evidence strictly.

A passage is relevant only if it directly helps answer
the user's actual question. Mere overlap on terms such as
HDB, CPF, resale flat, housing, or policy is not enough.

Set sufficient=true only when the relevant passages provide
enough factual support to give a useful grounded answer
without guessing.

If the evidence is unrelated, merely topical, or missing
important information needed to answer the question,
set sufficient=false.

If evidence is insufficient, suggest at most 2 targeted search queries.
If the question has multiple parts, decompose it so each query targets one missing part.
Do not repeat the original question unchanged unless necessary.

Return JSON only:

{{
  "sufficient": true,
  "relevant_indices": [1, 2],
  "reason": "Brief explanation",
  "missing_information": "What information is still missing, or empty if sufficient",
  "suggested_queries": [
    "Targeted search query 1",
    "Targeted search query 2"
  ]
}}
""".strip()

    client = _get_client()

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a strict evidence assessor "
                    "for a housing-policy RAG system. "
                    "Judge only whether the supplied passages "
                    "support the question. Do not answer the question."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        response_format={
            "type": "json_object"
        },
    )

    result = json.loads(
        response.choices[0].message.content
    )

    relevant_indices = []

    for index in result.get(
        "relevant_indices",
        [],
    ):
        if (
            isinstance(index, int)
            and 1 <= index <= len(evidence)
        ):
            relevant_indices.append(index)

    suggested_queries = result.get(
        "suggested_queries",
        [],
    )

    if not isinstance(suggested_queries, list):
        suggested_queries = []

    suggested_queries = [
        str(query).strip()
        for query in suggested_queries[:2]
        if str(query).strip()
    ]

    return {
        "sufficient": bool(
            result.get("sufficient")
        ),
        "relevant_indices": relevant_indices,
        "reason": str(
            result.get("reason", "")
        ),
        "missing_information": str(
            result.get("missing_information", "")
        ),
        "suggested_queries": suggested_queries,
    }