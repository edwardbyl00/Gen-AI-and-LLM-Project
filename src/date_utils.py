from collections import Counter
from datetime import date


def filter_by_effective_date(policies, query_date):
    """
    Keep policies that were already effective on the query date.
    Policies without an effective date are retained rather than guessed.
    """

    query_date = date.fromisoformat(query_date)

    filtered = []

    for policy in policies:
        effective_date = policy.get("effective_date")

        if not effective_date:
            filtered.append(policy)
            continue

        policy_date = date.fromisoformat(effective_date)

        if policy_date <= query_date:
            filtered.append(policy)

    return filtered


def select_latest_versions(policies):
    """
    For policies sharing the same policy_key, keep only the latest
    applicable version.

    Items without a policy_key are kept individually.
    """

    selected = {}
    unversioned = []

    for policy in policies:
        policy_key = policy.get("policy_key")

        if not policy_key:
            unversioned.append(policy)
            continue

        current = selected.get(policy_key)

        if current is None:
            selected[policy_key] = policy
            continue

        current_date = current.get("effective_date")
        new_date = policy.get("effective_date")

        if new_date and (
            not current_date
            or new_date > current_date
        ):
            selected[policy_key] = policy

    return unversioned + list(selected.values())


def audit_policy_dates(policies):
    """
    Check completeness of effective-date metadata.
    """

    total = len(policies)

    with_date = [
        policy
        for policy in policies
        if policy.get("effective_date")
    ]

    without_date = [
        policy
        for policy in policies
        if not policy.get("effective_date")
    ]

    missing_by_source = Counter(
        policy.get("source", "UNKNOWN")
        for policy in without_date
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
        "missing_by_source": dict(missing_by_source),
    }


def is_date_ready(report, min_coverage=0.8):
    """
    Return True only when effective-date coverage reaches
    the required threshold.
    """

    return report["date_coverage"] >= min_coverage