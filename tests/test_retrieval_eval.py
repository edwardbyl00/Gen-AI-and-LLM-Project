import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from policy_retriever import retrieve_policy_evidence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_PATH = PROJECT_ROOT / "data" / "mock" / "retrieval_eval.json"


with open(EVAL_PATH, "r", encoding="utf-8") as f:
    eval_cases = json.load(f)


hit_at_1 = 0
hit_at_3 = 0
requery_count = 0


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

    expected = case["expected_document_id"]

    if retrieved_ids and retrieved_ids[0] == expected:
        hit_at_1 += 1

    if expected in retrieved_ids[:3]:
        hit_at_3 += 1

    if result["requeried"]:
        requery_count += 1

    print(
        f"{case['id']} | expected={expected} | "
        f"retrieved={retrieved_ids} | "
        f"requeried={result['requeried']}"
    )


total = len(eval_cases)

print("\nResults")
print(f"Hit@1: {hit_at_1}/{total} = {hit_at_1 / total:.2%}")
print(f"Hit@3: {hit_at_3}/{total} = {hit_at_3 / total:.2%}")
print(f"Re-query triggered: {requery_count}/{total}")