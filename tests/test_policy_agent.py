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

print("\nPolicy agent tests passed.")