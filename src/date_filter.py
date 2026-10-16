import json
from datetime import datetime
from pathlib import Path


def load_policies():
    file_path = Path("data/mock/policies.json")

    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def filter_by_effective_date(policies, query_date):
    """
    Keep only policies that were already effective on query_date.
    """

    query_date = datetime.strptime(query_date, "%Y-%m-%d")

    valid_policies = []

    for policy in policies:
        effective_date = policy.get("effective_date")

        # If no effective date exists, keep it for now
        if not effective_date:
            valid_policies.append(policy)
            continue

        effective_date = datetime.strptime(effective_date, "%Y-%m-%d")

        if effective_date <= query_date:
            valid_policies.append(policy)

    return valid_policies

def select_latest_versions(policies):
    """
    If multiple versions of the same policy exist,
    keep only the newest applicable version.
    """

    latest = {}

    for policy in policies:
        policy_key = policy.get("policy_key")

        # Policies without versions are kept normally
        if not policy_key:
            latest[policy["document_id"]] = policy
            continue

        if policy_key not in latest:
            latest[policy_key] = policy
            continue

        current_date = datetime.strptime(
            policy["effective_date"], "%Y-%m-%d"
        )

        existing_date = datetime.strptime(
            latest[policy_key]["effective_date"], "%Y-%m-%d"
        )

        if current_date > existing_date:
            latest[policy_key] = policy

    return list(latest.values())


if __name__ == "__main__":
    policies = load_policies()

    results = filter_by_effective_date(
    policies,
    query_date="2026-06-01"
    )

    results = select_latest_versions(results)

    for policy in results:
        print(
            policy["document_id"],
            "|",
            policy["title"],
            "| effective:",
            policy["effective_date"]
        )