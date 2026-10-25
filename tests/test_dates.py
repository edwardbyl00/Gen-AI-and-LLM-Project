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

from retrieval import load_policies
from date_utils import (
    audit_policy_dates,
    is_date_ready,
)
from policy_agent import run_policy_agent


# --------------------------------------------------
# 1. Date metadata audit
# --------------------------------------------------

policies = load_policies()

report = audit_policy_dates(
    policies
)

print("Date metadata audit")
print(report)

assert report["total"] == len(policies)

assert (
    report["with_effective_date"]
    + report["missing_effective_date"]
    == report["total"]
)

assert is_date_ready(report) is True


# --------------------------------------------------
# 2. Incomplete metadata
# --------------------------------------------------

incomplete_policies = [
    {
        "document_id": "A",
        "source": "HDB",
        "effective_date": "2026-01-01",
    },
    {
        "document_id": "B",
        "source": "HDB",
        "effective_date": None,
    },
    {
        "document_id": "C",
        "source": "CPF",
        "effective_date": None,
    },
]

incomplete_report = audit_policy_dates(
    incomplete_policies
)

print(
    "\nIncomplete metadata audit"
)

print(incomplete_report)

assert (
    is_date_ready(incomplete_report)
    is False
)


# --------------------------------------------------
# 3. Policy version in 2025
# --------------------------------------------------

result_2025 = run_policy_agent(
    question="What CPF housing rule applied?",
    query_date="2025-06-01",
)

ids_2025 = [
    item["document_id"]
    for item
    in result_2025[
        "retrieval"
    ]["evidence"]
]

print(
    "\n2025 results:",
    ids_2025,
)

assert "OLD01" in ids_2025
assert "NEW01" not in ids_2025


# --------------------------------------------------
# 4. Policy version in 2026
# --------------------------------------------------

result_2026 = run_policy_agent(
    question="What CPF housing rule applies?",
    query_date="2026-06-01",
)

ids_2026 = [
    item["document_id"]
    for item
    in result_2026[
        "retrieval"
    ]["evidence"]
]

print(
    "2026 results:",
    ids_2026,
)

assert "NEW01" in ids_2026
assert "OLD01" not in ids_2026

print(
    "\nAll date tests passed."
)