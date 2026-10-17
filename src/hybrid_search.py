import json
import re
from pathlib import Path

from rank_bm25 import BM25Okapi


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


def bm25_search(query, policies, top_k=3):
    """
    Search policy text using BM25 keyword retrieval.
    """

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