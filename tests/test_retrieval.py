import json
import sys
from pathlib import Path

sys.path.append(
    str(
        Path(__file__)
        .resolve()
        .parents[1]
        / "src"
    )
)

from retrieval import (
    load_policies,
    search_with_requery,
)
from policy_retriever import (
    retrieve_policy_evidence,
)
from hybrid_retriever import (
    reciprocal_rank_fusion,
    hybrid_retrieve,
)


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

EVAL_PATH = (
    PROJECT_ROOT
    / "data"
    / "mock"
    / "retrieval_eval.json"
)


# --------------------------------------------------
# 1. Re-query
# --------------------------------------------------

policies = load_policies()

result = search_with_requery(
    query="Can I use OA savings for my flat?",
    policies=policies,
    query_date="2026-06-01",
    top_k=3,
)

assert result["requeried"] is True
assert result["rewrite_accepted"] is True

assert (
    "Ordinary Account"
    in result["final_query"]
)

assert (
    result["results"][0][0]["document_id"]
    == "C01"
)

print("Re-query test passed.")


# --------------------------------------------------
# 2. Retrieval evaluation
# --------------------------------------------------

with open(
    EVAL_PATH,
    "r",
    encoding="utf-8",
) as f:
    eval_cases = json.load(f)


hit_at_1 = 0
hit_at_3 = 0


for case in eval_cases:
    result = retrieve_policy_evidence(
        question=case["question"],
        query_date=case["query_date"],
        top_k=3,
    )

    retrieved_ids = [
        item["document_id"]
        for item in result["evidence"]
    ]

    expected = (
        case["expected_document_id"]
    )

    if (
        retrieved_ids
        and retrieved_ids[0]
        == expected
    ):
        hit_at_1 += 1

    if expected in retrieved_ids[:3]:
        hit_at_3 += 1


total = len(eval_cases)

print(
    f"Hit@1: {hit_at_1}/{total}"
)

print(
    f"Hit@3: {hit_at_3}/{total}"
)

assert hit_at_1 >= 4
assert hit_at_3 == total

print(
    "Retrieval evaluation test passed."
)


# --------------------------------------------------
# 3. RRF
# --------------------------------------------------

bm25_results = [
    (
        {
            "document_id": "C01",
            "title": "CPF Housing",
        },
        3.2,
    ),
    (
        {
            "document_id": "H06",
            "title": "MOP",
        },
        2.1,
    ),
    (
        {
            "document_id": "H01",
            "title": "HDB Eligibility",
        },
        1.4,
    ),
]


dense_results = [
    {
        "document_id": "H01",
        "title": "HDB Eligibility",
    },
    {
        "document_id": "C01",
        "title": "CPF Housing",
    },
    {
        "document_id": "NEW01",
        "title": "Updated CPF Rule",
    },
]


fused = reciprocal_rank_fusion(
    [
        bm25_results,
        dense_results,
    ]
)

assert (
    fused[0]["document_id"]
    == "C01"
)

print("RRF test passed.")


# --------------------------------------------------
# 4. Hybrid retriever
# --------------------------------------------------

hybrid_results = hybrid_retrieve(
    bm25_results=bm25_results,
    dense_results=dense_results,
    top_k=3,
)

assert len(hybrid_results) == 3

assert (
    hybrid_results[0]["document_id"]
    == "C01"
)

print("Hybrid retrieval test passed.")

print(
    "\nAll retrieval tests passed."
)