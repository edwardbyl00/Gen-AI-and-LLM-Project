import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from policy_agent import run_policy_agent


# --------------------------------------------------
# Case 1: Answerable question
# --------------------------------------------------

result = run_policy_agent(
    question="Can I use OA savings for my flat?",
    query_date="2026-06-01",
)

print("\nANSWERABLE CASE")
print("Decision:", result["decision"])
print("Trace:")

for step in result["trace"]:
    print(step)

assert result["decision"] == "ANSWER_READY"

steps = [
    item["step"]
    for item in result["trace"]
]

assert "RETRIEVE" in steps
assert "REQUERY" in steps
assert "CHECK_EVIDENCE" in steps
assert "ANSWER_READY" in steps


# --------------------------------------------------
# Case 2: Completely unrelated question
# --------------------------------------------------

result = run_policy_agent(
    question="What colour is the moon made of xyzabc?",
    query_date="2026-06-01",
)

print("\nUNSUPPORTED CASE")
print("Decision:", result["decision"])
print("Trace:")

for step in result["trace"]:
    print(step)

assert result["decision"] == "ABSTAIN"

# --------------------------------------------------
# Case 3: Hybrid retrieval
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


hybrid_result = run_policy_agent(
    question="Can I use OA savings for my flat?",
    query_date="2026-06-01",
    dense_results=dense_results,
)


print("\nHYBRID CASE")
print(
    "Mode:",
    hybrid_result["retrieval"]["retrieval_mode"],
)
print(
    "Decision:",
    hybrid_result["decision"],
)

hybrid_ids = [
    item["document_id"]
    for item in hybrid_result[
        "retrieval"
    ]["evidence"]
]

print("Results:", hybrid_ids)


assert (
    hybrid_result["retrieval"][
        "retrieval_mode"
    ]
    == "hybrid"
)

assert hybrid_result["decision"] == "ANSWER_READY"

assert hybrid_ids[0] == "C01"

print("\nPolicy agent tests passed.")