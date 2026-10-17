import json
import re
from pathlib import Path

from rank_bm25 import BM25Okapi
from date_filter import filter_by_effective_date, select_latest_versions

def load_policies():
    file_path = Path("data/mock/policies.json")

    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def tokenize(text):
    """
    Very simple tokenizer for BM25.
    Lowercases text and keeps words/numbers.
    """
    return re.findall(r"\b\w+\b", text.lower())


def bm25_search(query, policies, query_date=None, top_k=3):
    """
    Search policy text using BM25 keyword retrieval.

    If query_date is provided, only policies applicable
    on that date are searched.
    """

    if query_date:
        policies = filter_by_effective_date(
            policies,
            query_date=query_date
        )

        policies = select_latest_versions(policies)

    corpus = []

    for policy in policies:
        searchable_text = (
            f"{policy['title']} "
            f"{policy['category']} "
            f"{policy['text']}"
        )

        corpus.append(tokenize(searchable_text))

    bm25 = BM25Okapi(corpus)

    tokenized_query = tokenize(query)
    scores = bm25.get_scores(tokenized_query)

    ranked = sorted(
        zip(policies, scores),
        key=lambda x: x[1],
        reverse=True
    )

    return ranked[:top_k]


if __name__ == "__main__":
    policies = load_policies()

    query = "Can I use CPF to buy a home?"

    results = bm25_search(
        query=query,
        policies=policies,
        query_date="2026-06-01",
        top_k=3
    )

    print(f"\nQuery: {query}\n")

    for policy, score in results:
        print(
            policy["document_id"],
            "|",
            policy["title"],
            "| score:",
            round(float(score), 3)
        )