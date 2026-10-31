import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from policy_agent import run_policy_agent


PILOT_IDS = ["H01", "H07", "H14", "H15", "H23", "H29", "C01", "C04", "C06", "C10",]

RUNS = 3


with open(
    ROOT / "evaluation" / "retrieval" / "ground_truth_40q.csv",
    encoding="utf-8-sig",
    newline="",
) as f:
    rows = {
        row["question_id"]: row
        for row in csv.DictReader(f)
    }


all_agreements = []

for qid in PILOT_IDS:
    question = rows[qid]["question"]
    decisions = []

    print("\n" + "=" * 60)
    print(qid, question)

    for run_number in range(1, RUNS + 1):
        result = run_policy_agent(
            question,
            top_k=10,
            use_dense=True,
            use_llm_assessor=True,
        )

        decision = result["decision"]
        decisions.append(decision)

        print(
            f"Run {run_number}: {decision}"
        )

    counts = Counter(decisions)
    majority_decision, majority_count = (
        counts.most_common(1)[0]
    )

    agreement = majority_count / RUNS
    all_agreements.append(agreement)

    print(
        "Majority:",
        majority_decision,
        f"({majority_count}/{RUNS})",
    )


print("\n" + "=" * 60)
print("REPEATABILITY SUMMARY")
print("=" * 60)

print(
    "Mean decision agreement:",
    round(
        sum(all_agreements)
        / len(all_agreements),
        3,
    ),
)

print(
    "Fully stable questions:",
    sum(
        agreement == 1.0
        for agreement in all_agreements
    ),
    "/",
    len(all_agreements),
)