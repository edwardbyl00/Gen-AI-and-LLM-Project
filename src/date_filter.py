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


if __name__ == "__main__":
    policies = load_policies()

    results = filter_by_effective_date(
        policies,
        query_date="2025-06-01"
    )

    for policy in results:
        print(
            policy["document_id"],
            "|",
            policy["title"],
            "| effective:",
            policy["effective_date"]
        )