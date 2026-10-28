import json
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import OpenAI
import time


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
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")

    if not api_key:
        raise ValueError(
            "No API key found. Add OPENAI_API_KEY or LLM_API_KEY to .env."
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

Assess the evidence strictly against the user's actual question.

A passage is relevant only if it directly helps answer the question.
Mere overlap on terms such as HDB, CPF, resale flat, housing, or policy
is not enough.

Set sufficient=true when the passages provide enough policy evidence
to give a useful grounded answer.

A useful answer may be CONDITIONAL. Do not require all user-specific
facts to be known before setting sufficient=true.

For example:
- If the question asks what options may be available, the evidence is
  sufficient if it supports the relevant options and conditions.
- If the question asks what additional facts are needed, the evidence
  is sufficient if it identifies the applicable rules and which user
  facts would determine the outcome.
- Missing user information such as household type, remaining lease,
  property ownership, or loan type is NOT by itself a reason to mark
  the evidence insufficient.

Set sufficient=false only when important POLICY INFORMATION needed to
answer the question is missing, or when the passages are merely
topically related and do not support a grounded answer.

If evidence is insufficient because POLICY INFORMATION is missing,
suggest at most 2 targeted search queries.
Do not generate new searches merely because user-specific information
is missing.

Suggested queries are used to search a LOCAL HDB/CPF policy corpus.

Therefore:
- Write short, retrieval-focused keyword queries.
- Preserve the important policy concept, household type, transaction type,
  eligibility condition, age, citizenship, or CPF rule from the question.
- Do NOT use web-search operators such as "site:".
- Do NOT include URLs or domain names.
- Do NOT write long conversational questions.
- Each query should target one missing policy rule.

Good:
"HDB new flat eligibility married Singapore citizen permanent resident spouse"

Bad:
"site:hdb.gov.sg can a Singapore citizen with PR spouse buy BTO"

Return JSON only:

{{
  "sufficient": true,
  "answer_mode": "conditional",
  "relevant_indices": [1, 2],
  "reason": "Brief explanation",
  "missing_policy_information": "",
  "missing_user_information": [
    "Any user facts still needed to determine the final outcome"
  ],
  "suggested_queries": []
}}
""".strip()

    start = time.perf_counter()

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

    elapsed_seconds = time.perf_counter() - start

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

    missing_user_information = result.get(
        "missing_user_information",
        [],
    )

    if not isinstance(missing_user_information, list):
        missing_user_information = []

    usage = response.usage

    return {
        "sufficient": bool(
            result.get("sufficient")
        ),
        "answer_mode": str(
            result.get("answer_mode", "direct")
        ),
        "relevant_indices": relevant_indices,
        "reason": str(
            result.get("reason", "")
        ),
        "missing_policy_information": str(
            result.get("missing_policy_information", "")
        ),
        "missing_user_information": [
            str(item)
            for item in missing_user_information
        ],
        "suggested_queries": suggested_queries,
        "_usage": {
            "input_tokens": usage.prompt_tokens,
            "output_tokens": usage.completion_tokens,
            "total_tokens": (
                usage.prompt_tokens
                + usage.completion_tokens
            ),
            "latency_seconds": round(
                elapsed_seconds,
                3,
            ),
        },
    }