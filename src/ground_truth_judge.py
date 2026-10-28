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


GROUND_TRUTH_RUBRIC = {
    "answer_correctness": {
        "description": (
            "Is the answer consistent with the verified benchmark "
            "ground truth and does it avoid contradicting the core policy?"
        ),
        "score_range": [0, 2],
    },
    "ground_truth_completeness": {
        "description": (
            "Does the answer cover the important verified policy points "
            "and conditions needed for a useful answer?"
        ),
        "score_range": [0, 2],
    },
    "unsupported_claims": {
        "description": (
            "Does the answer avoid factual claims unsupported by either "
            "the verified ground truth or the retrieved evidence?"
        ),
        "score_range": [0, 2],
    },
    "appropriate_conditionality": {
        "description": (
            "Does the answer correctly distinguish policy rules from "
            "missing user-specific facts and answer conditionally when needed?"
        ),
        "score_range": [0, 2],
    },
    "appropriate_abstention": {
        "description": (
            "Does the system abstain when its available evidence is "
            "insufficient, and avoid unnecessary abstention when a useful "
            "grounded answer is possible?"
        ),
        "score_range": [0, 2],
    },
}


def _load_model():
    with CONFIG_PATH.open(
        "r",
        encoding="utf-8",
    ) as f:
        config = yaml.safe_load(f) or {}

    model = (
        config.get("judge", {}).get("model")
        or config.get("llm", {}).get("model")
    )

    if not model:
        raise ValueError(
            "No judge or LLM model found in config.yaml"
        )

    return model


MODEL = _load_model()

# Keep the same accounting assumptions as src/llm_judge.py
INPUT_PRICE = 2.50
OUTPUT_PRICE = 15.00


def _get_client():
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY was not found in .env"
        )

    return OpenAI(api_key=api_key)


def _format_evidence(evidence):
    blocks = []

    for index, item in enumerate(
        evidence,
        start=1,
    ):
        blocks.append(
            f"""
[Retrieved Evidence {index}]
Chunk ID: {item.get("chunk_id")}
Title: {item.get("title")}
Source: {item.get("source")}
Effective date: {item.get("effective_date")}
Text:
{item.get("text")}
""".strip()
        )

    if not blocks:
        return "(No retrieved evidence was supplied to synthesis.)"

    return "\n\n".join(blocks)


def build_ground_truth_prompt(
    question,
    answer,
    decision,
    declined,
    evidence,
    coverage_status,
    supporting_evidence,
    required_conditions,
    review_notes="",
):
    rubric_text = []

    for name, criterion in GROUND_TRUTH_RUBRIC.items():
        rubric_text.append(
            f"- {name}: {criterion['description']} "
            "(0 = poor, 1 = partial, 2 = fully satisfactory)"
        )

    return f"""
Evaluate the SYSTEM OUTPUT against the VERIFIED BENCHMARK GROUND TRUTH.

Important evaluation rules:

1. The benchmark fields below represent VERIFIED CORE EVIDENCE.
   They are authoritative for the central answer, but they are not
   necessarily an exhaustive list of every valid policy detail.

2. Retrieved evidence may contain additional valid details.
   Do not penalise a correct additional detail merely because it is
   absent from the short benchmark summary, provided it is supported
   by the retrieved evidence and does not contradict the benchmark.

3. Missing USER INFORMATION is different from missing POLICY EVIDENCE.
   A conditional answer may be fully correct when the final outcome
   depends on facts the user has not supplied.

4. For coverage_status=NOT_COVERED:
   - a clear, safe abstention should normally receive full credit for
     appropriate_abstention;
   - do not penalise the answer merely because it does not provide a
     substantive policy answer that the corpus cannot support.

5. For coverage_status=FULL:
   - if the system retrieved enough evidence, unnecessary abstention
     should reduce completeness and/or appropriate_abstention;
   - if the system's retrieved evidence is genuinely insufficient,
     a cautious abstention is safer than inventing an answer.
     Do NOT automatically score such an abstention as a total failure.

6. Judge the end-to-end system behaviour, not an oracle system that
   magically knows evidence that was never retrieved.

Question:
{question}

System decision:
{decision}

Synthesis declined:
{declined}

System answer:
{answer}

Benchmark coverage status:
{coverage_status}

Verified supporting evidence:
{supporting_evidence}

Verified required conditions:
{required_conditions}

Benchmark review notes:
{review_notes or "(none)"}

Evidence actually available to the system:
{_format_evidence(evidence)}

Rubric:
{chr(10).join(rubric_text)}

Return JSON only:

{{
  "answer_correctness": 0,
  "ground_truth_completeness": 0,
  "unsupported_claims": 0,
  "appropriate_conditionality": 0,
  "appropriate_abstention": 0,
  "total_score": 0,
  "reason": "Brief explanation grounded in the benchmark and retrieved evidence"
}}
""".strip()


def validate_ground_truth_judge_output(raw_output):
    try:
        result = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Ground-truth judge output was not valid JSON."
        ) from exc

    score_fields = [
        "answer_correctness",
        "ground_truth_completeness",
        "unsupported_claims",
        "appropriate_conditionality",
        "appropriate_abstention",
    ]

    for field in score_fields:
        if field not in result:
            raise ValueError(
                f"Missing ground-truth judge field: {field}"
            )

        if result[field] not in {0, 1, 2}:
            raise ValueError(
                f"Invalid score for {field}: "
                f"{result[field]}"
            )

    result["total_score"] = sum(
        result[field]
        for field in score_fields
    )

    if not isinstance(
        result.get("reason"),
        str,
    ):
        raise ValueError(
            "Ground-truth judge reason must be a string."
        )

    return result


def judge_against_ground_truth(
    question,
    answer,
    decision,
    declined,
    evidence,
    coverage_status,
    supporting_evidence,
    required_conditions,
    review_notes="",
):
    client = _get_client()

    prompt = build_ground_truth_prompt(
        question=question,
        answer=answer,
        decision=decision,
        declined=declined,
        evidence=evidence,
        coverage_status=coverage_status,
        supporting_evidence=supporting_evidence,
        required_conditions=required_conditions,
        review_notes=review_notes,
    )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a strict evaluator of a housing-policy "
                    "RAG system. Compare the system output against the "
                    "verified benchmark and the evidence actually "
                    "available to the system. Return JSON only."
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
        max_completion_tokens=1200,
    )

    raw_output = (
        response
        .choices[0]
        .message
        .content
    )

    result = validate_ground_truth_judge_output(
        raw_output
    )

    usage = response.usage

    cost = (
        usage.prompt_tokens
        / 1_000_000
        * INPUT_PRICE
        + usage.completion_tokens
        / 1_000_000
        * OUTPUT_PRICE
    )

    return {
        "judgement": result,
        "usage": {
            "input_tokens": usage.prompt_tokens,
            "output_tokens": usage.completion_tokens,
            "cost_usd": round(cost, 6),
        },
    }