import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from retrieval import bm25_search, load_policies
from policy_retriever import retrieve_policy_evidence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_PATH = PROJECT_ROOT / "data" / "mock" / "retrieval_eval.json"

RESULTS_DIR = PROJECT_ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)


with open(EVAL_PATH, "r", encoding="utf-8") as f:
    eval_cases = json.load(f)

policies = load_policies()


baseline_hit1 = 0
baseline_hit3 = 0

advanced_hit1 = 0
advanced_hit3 = 0


for case in eval_cases:
    question = case["question"]
    expected = case["expected_document_id"]

    # --------------------------------------------------
    # BASELINE:
    # Plain BM25 retrieval only.
    # No date filtering.
    # No latest-version selection.
    # No re-query.
    # --------------------------------------------------
    baseline_results = bm25_search(
        query=question,
        policies=policies,
        top_k=3,
    )

    baseline_ids = [
        item[0]["document_id"]
        for item in baseline_results
    ]

    # --------------------------------------------------
    # ADVANCED P5:
    # Date-aware retrieval + version handling + re-query.
    # --------------------------------------------------
    advanced_result = retrieve_policy_evidence(
        question=question,
        query_date=case["query_date"],
        top_k=3,
        policies=policies,
    )

    advanced_ids = [
        item["document_id"]
        for item in advanced_result["evidence"]
    ]

    if baseline_ids and baseline_ids[0] == expected:
        baseline_hit1 += 1

    if expected in baseline_ids[:3]:
        baseline_hit3 += 1

    if advanced_ids and advanced_ids[0] == expected:
        advanced_hit1 += 1

    if expected in advanced_ids[:3]:
        advanced_hit3 += 1

    print(f"\n{case['id']} | {question}")
    print(f"Expected : {expected}")
    print(f"Baseline : {baseline_ids}")
    print(f"Advanced : {advanced_ids}")


total = len(eval_cases)

print("\n" + "=" * 60)
print("RETRIEVAL COMPARISON")
print("=" * 60)

print(
    f"Baseline Hit@1: "
    f"{baseline_hit1}/{total} = {baseline_hit1 / total:.2%}"
)

print(
    f"Advanced Hit@1: "
    f"{advanced_hit1}/{total} = {advanced_hit1 / total:.2%}"
)

print(
    f"Baseline Hit@3: "
    f"{baseline_hit3}/{total} = {baseline_hit3 / total:.2%}"
)

print(
    f"Advanced Hit@3: "
    f"{advanced_hit3}/{total} = {advanced_hit3 / total:.2%}"
)

baseline_h1_rate = baseline_hit1 / total
advanced_h1_rate = advanced_hit1 / total

baseline_h3_rate = baseline_hit3 / total
advanced_h3_rate = advanced_hit3 / total

print("\nImprovement")

print(
    f"Hit@1 change: "
    f"{(advanced_h1_rate - baseline_h1_rate) * 100:+.1f} percentage points"
)

print(
    f"Hit@3 change: "
    f"{(advanced_h3_rate - baseline_h3_rate) * 100:+.1f} percentage points"
)

results_summary = {
    "dataset": "mock_retrieval_eval",
    "total_questions": total,
    "baseline": {
        "hit_at_1": baseline_h1_rate,
        "hit_at_3": baseline_h3_rate,
    },
    "advanced": {
        "hit_at_1": advanced_h1_rate,
        "hit_at_3": advanced_h3_rate,
    },
    "improvement_percentage_points": {
        "hit_at_1": round(
            (advanced_h1_rate - baseline_h1_rate) * 100, 1
        ),
        "hit_at_3": round(
            (advanced_h3_rate - baseline_h3_rate) * 100, 1
        ),
    },
}

output_path = RESULTS_DIR / "mock_retrieval_comparison.json"

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(results_summary, f, indent=2)

print(f"\nSaved results to: {output_path}")