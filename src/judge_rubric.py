import json

JUDGE_RUBRIC = {
    "evidence_support": {
        "description": "Are the answer's factual claims supported by the retrieved evidence?",
        "score_range": [0, 2],
    },
    "policy_currency": {
        "description": "Does the answer rely on the correct applicable policy version?",
        "score_range": [0, 2],
    },
    "citation_relevance": {
        "description": "Do the cited passages actually support the answer?",
        "score_range": [0, 2],
    },
    "unsupported_claims": {
        "description": "Does the answer avoid introducing information not supported by the evidence?",
        "score_range": [0, 2],
    },
    "appropriate_abstention": {
        "description": "If evidence is insufficient, does the system avoid guessing?",
        "score_range": [0, 2],
    },
}


def max_score():
    return sum(
        item["score_range"][1]
        for item in JUDGE_RUBRIC.values()
    )

def build_judge_prompt(question, answer, evidence):
    """
    Build a structured prompt for an LLM judge.
    """

    evidence_text = "\n\n".join(
        [
            f"[Evidence {i + 1}]\n"
            f"Title: {item.get('title')}\n"
            f"Source: {item.get('source')}\n"
            f"Effective date: {item.get('effective_date')}\n"
            f"Text: {item.get('text')}"
            for i, item in enumerate(evidence)
        ]
    )

    rubric_text = "\n".join(
        [
            f"- {name}: {item['description']} "
            f"(score {item['score_range'][0]}-{item['score_range'][1]})"
            for name, item in JUDGE_RUBRIC.items()
        ]
    )

    return f"""
You are evaluating an AI-generated housing policy answer.

Question:
{question}

Answer:
{answer}

Retrieved evidence:
{evidence_text}

Score the answer using this rubric:

{rubric_text}

Scoring meaning:
0 = poor / incorrect
1 = partially satisfactory
2 = fully satisfactory

Return JSON only in this format:

{{
  "evidence_support": 0,
  "policy_currency": 0,
  "citation_relevance": 0,
  "unsupported_claims": 0,
  "appropriate_abstention": 0,
  "total_score": 0,
  "reason": "brief explanation"
}}
""".strip()

def validate_judge_output(raw_output):
    """
    Parse and validate JSON returned by the LLM judge.
    """

    try:
        result = json.loads(raw_output)
    except json.JSONDecodeError as e:
        raise ValueError("Judge output is not valid JSON.") from e

    required_scores = [
        "evidence_support",
        "policy_currency",
        "citation_relevance",
        "unsupported_claims",
        "appropriate_abstention",
    ]

    for field in required_scores:
        if field not in result:
            raise ValueError(f"Missing judge field: {field}")

        if result[field] not in (0, 1, 2):
            raise ValueError(
                f"{field} must be 0, 1, or 2."
            )

    expected_total = sum(
        result[field]
        for field in required_scores
    )

    if result.get("total_score") != expected_total:
        raise ValueError(
            f"Incorrect total_score. "
            f"Expected {expected_total}, "
            f"got {result.get('total_score')}."
        )

    if not isinstance(result.get("reason"), str):
        raise ValueError("Judge reason must be a string.")

    return result


if __name__ == "__main__":
    sample_output = """
    {
      "evidence_support": 2,
      "policy_currency": 2,
      "citation_relevance": 2,
      "unsupported_claims": 2,
      "appropriate_abstention": 1,
      "total_score": 9,
      "reason": "The answer is well supported by the retrieved evidence."
    }
    """

    result = validate_judge_output(sample_output)

    print("Judge output valid.")
    print(result)