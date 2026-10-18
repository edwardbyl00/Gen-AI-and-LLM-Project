import sys
from pathlib import Path
from unittest.mock import patch

sys.path.append(
    str(
        Path(__file__)
        .resolve()
        .parents[1]
        / "src"
    )
)

from pipeline import evaluate_candidate_answer


fake_judge_result = {
    "judgement": {
        "evidence_support": 2,
        "policy_currency": 2,
        "citation_relevance": 2,
        "unsupported_claims": 2,
        "appropriate_abstention": 2,
        "total_score": 10,
        "reason": "Mock judge result.",
    },
    "usage": {
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
    },
}


with patch(
    "pipeline.judge_answer",
    return_value=fake_judge_result,
):
    result = evaluate_candidate_answer(
        question="Can I use OA savings for my flat?",
        answer=(
            "CPF Ordinary Account savings "
            "may be used for eligible "
            "housing purchases."
        ),
        query_date="2026-06-01",
    )


print("Agent decision:", result["agent_decision"])
print("Retrieval mode:", result["retrieval_mode"])
print(
    "Judge score:",
    result["judge"]["judgement"]["total_score"],
)


assert result["agent_decision"] == "ANSWER_READY"
assert result["retrieval_mode"] == "bm25"
assert len(result["evidence"]) > 0

assert (
    result["judge"]["judgement"]["total_score"]
    == 10
)

assert (
    result["judge"]["usage"]["cost_usd"]
    == 0.0
)

print("\nEnd-to-end pipeline test passed.")

# --------------------------------------------------
# Hybrid pipeline case
# --------------------------------------------------

dense_results = [
    {
        "document_id": "H01",
        "title": "HDB Eligibility",
        "source": "HDB",
        "category": "policy",
        "effective_date": "2026-01-01",
        "text": "Eligibility requirements for HDB housing.",
    },
    {
        "document_id": "C01",
        "title": "Using CPF to Buy a Home",
        "source": "CPF",
        "category": "policy",
        "effective_date": "2026-01-01",
        "text": (
            "CPF Ordinary Account savings may be used "
            "for eligible housing purchases."
        ),
    },
]


with patch(
    "pipeline.judge_answer",
    return_value=fake_judge_result,
):
    hybrid_result = evaluate_candidate_answer(
        question="Can I use OA savings for my flat?",
        answer=(
            "CPF Ordinary Account savings may be used "
            "for eligible housing purchases."
        ),
        query_date="2026-06-01",
        dense_results=dense_results,
    )


print("\nHybrid pipeline")
print(
    "Agent decision:",
    hybrid_result["agent_decision"],
)
print(
    "Retrieval mode:",
    hybrid_result["retrieval_mode"],
)
print(
    "Top evidence:",
    hybrid_result["evidence"][0]["document_id"],
)


assert (
    hybrid_result["agent_decision"]
    == "ANSWER_READY"
)

assert (
    hybrid_result["retrieval_mode"]
    == "hybrid"
)

assert (
    hybrid_result["evidence"][0]["document_id"]
    == "C01"
)

assert (
    hybrid_result["judge"]["judgement"]["total_score"]
    == 10
)

print("\nHybrid pipeline test passed.")

# --------------------------------------------------
# Unsupported / abstention pipeline case
# --------------------------------------------------

with patch(
    "pipeline.judge_answer",
    return_value=fake_judge_result,
):
    abstain_result = evaluate_candidate_answer(
        question="What colour is the moon made of xyzabc?",
        answer=(
            "The retrieved evidence does not provide enough "
            "information to answer this question."
        ),
        query_date="2026-06-01",
    )


print("\nAbstention pipeline")
print(
    "Agent decision:",
    abstain_result["agent_decision"],
)
print(
    "Agent reason:",
    abstain_result["agent_reason"],
)


assert (
    abstain_result["agent_decision"]
    == "ABSTAIN"
)

assert (
    abstain_result["retrieval_mode"]
    == "bm25"
)

print("\nAbstention pipeline test passed.")