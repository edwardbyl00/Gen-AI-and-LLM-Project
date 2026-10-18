from collections import Counter


def audit_policy_dates(policies):
    """
    Check how complete the policy date metadata is.
    """

    total = len(policies)

    with_date = [
        p for p in policies
        if p.get("effective_date")
    ]

    without_date = [
        p for p in policies
        if not p.get("effective_date")
    ]

    source_missing = Counter(
        p.get("source", "UNKNOWN")
        for p in without_date
    )

    coverage = (
        len(with_date) / total
        if total > 0
        else 0.0
    )

    return {
        "total": total,
        "with_effective_date": len(with_date),
        "missing_effective_date": len(without_date),
        "date_coverage": coverage,
        "missing_by_source": dict(source_missing),
    }

def is_date_ready(report, min_coverage=0.8):
    """
    Return True only when enough policies have effective-date metadata.
    """

    return report["date_coverage"] >= min_coverage