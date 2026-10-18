import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from policy_agent import run_policy_agent


# --------------------------------------------------
# 2025 should use OLD01
# --------------------------------------------------

result_2025 = run_policy_agent(
    question="What CPF housing rule applied?",
    query_date="2025-06-01",
)

ids_2025 = [
    item["document_id"]
    for item in result_2025["retrieval"]["evidence"]
]

print("\n2025 results:", ids_2025)

assert "OLD01" in ids_2025
assert "NEW01" not in ids_2025


# --------------------------------------------------
# 2026 should use NEW01
# --------------------------------------------------

result_2026 = run_policy_agent(
    question="What CPF housing rule applies?",
    query_date="2026-06-01",
)

ids_2026 = [
    item["document_id"]
    for item in result_2026["retrieval"]["evidence"]
]

print("2026 results:", ids_2026)

assert "NEW01" in ids_2026
assert "OLD01" not in ids_2026


print("\nDate-aware policy agent tests passed.")