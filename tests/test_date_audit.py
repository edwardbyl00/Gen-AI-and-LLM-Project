import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from hybrid_search import load_policies
from date_audit import audit_policy_dates, is_date_ready


# --------------------------------------------------
# Test 1: Current mock dataset
# --------------------------------------------------

policies = load_policies()

report = audit_policy_dates(policies)

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
# Test 2: Simulate incomplete metadata
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

incomplete_report = audit_policy_dates(incomplete_policies)

print("\nIncomplete metadata audit")
print(incomplete_report)

assert is_date_ready(incomplete_report) is False

print("\nDate readiness gate test passed.")