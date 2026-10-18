import json
import re
from pathlib import Path

from rank_bm25 import BM25Okapi

from date_utils import (
    filter_by_effective_date,
    select_latest_versions,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOCK_POLICY_PATH = PROJECT_ROOT / "data" / "mock" / "policies.json"


STOPWORDS = {"a", "an", "the", "i", "my", "me", "can", "could", "do", "does",
    "is", "are", "to", "for", "of", "in", "on", "with", "use", "using",
}


def load_policies():
    with open(MOCK_POLICY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def tokenize(text):
    return re.findall(r"\b\w+\b", text.lower())


def _searchable_text(policy):
    title = policy.get("title") or ""

    category = (
        policy.get("category")
        or policy.get("document_type")
        or ""
    )

    text = (
        policy.get("text")
        or policy.get("content")
        or ""
    )

    return f"{title} {category} {text}"


def bm25_search(
    query,
    policies,
    top_k=3,
    query_date=None,
):
    """
    BM25 keyword retrieval with optional date filtering.
    """

    candidate_policies = list(policies)

    if query_date:
        candidate_policies = filter_by_effective_date(
            candidate_policies,
            query_date,
        )

        candidate_policies = select_latest_versions(
            candidate_policies
        )

    if not candidate_policies:
        return []

    corpus = [
        tokenize(_searchable_text(policy))
        for policy in candidate_policies
    ]

    bm25 = BM25Okapi(corpus)

    query_tokens = tokenize(query)

    scores = bm25.get_scores(query_tokens)

    ranked = sorted(
        zip(candidate_policies, scores),
        key=lambda item: item[1],
        reverse=True,
    )

    return ranked[:top_k]


def get_meaningful_tokens(text):
    return {
        token
        for token in tokenize(text)
        if token not in STOPWORDS
    }


def get_query_coverage(results, query):
    """
    Measure how much of the meaningful query vocabulary
    appears in the top retrieved passage.
    """

    if not results:
        return 0.0

    top_policy, _ = results[0]

    query_tokens = get_meaningful_tokens(query)

    if not query_tokens:
        return 1.0

    document_tokens = get_meaningful_tokens(
        _searchable_text(top_policy)
    )

    matched = query_tokens.intersection(document_tokens)

    return len(matched) / len(query_tokens)


def should_requery(
    results,
    query,
    min_coverage=0.5,
):
    if not results:
        return True

    _, top_score = results[0]

    if float(top_score) <= 0:
        return True

    coverage = get_query_coverage(results, query)

    return coverage < min_coverage


def rewrite_query(query):
    """
    Lightweight domain-aware query expansion.
    """

    replacements = {
        "OA": "Ordinary Account",
        "MOP": "Minimum Occupation Period",
        "EHG": "Enhanced CPF Housing Grant",
    }

    rewritten = query

    for short_form, expanded_form in replacements.items():
        rewritten = re.sub(
            rf"\b{re.escape(short_form)}\b",
            expanded_form,
            rewritten,
            flags=re.IGNORECASE,
        )

    return rewritten


def search_with_requery(
    query,
    policies,
    query_date=None,
    top_k=3,
):
    """
    Run initial BM25 retrieval and conditionally retry
    using a rewritten query.
    """

    initial_results = bm25_search(
        query=query,
        policies=policies,
        top_k=top_k,
        query_date=query_date,
    )

    initial_coverage = get_query_coverage(
        initial_results,
        query,
    )

    print(
        f"Initial query coverage: "
        f"{initial_coverage:.2f}"
    )

    if not should_requery(initial_results, query):
        return {
            "original_query": query,
            "final_query": query,
            "requeried": False,
            "rewrite_accepted": False,
            "original_coverage": initial_coverage,
            "final_coverage": initial_coverage,
            "results": initial_results,
        }

    rewritten_query = rewrite_query(query)

    rewritten_results = bm25_search(
        query=rewritten_query,
        policies=policies,
        top_k=top_k,
        query_date=query_date,
    )

    rewritten_coverage = get_query_coverage(
        rewritten_results,
        rewritten_query,
    )

    print(
        f"Rewritten query coverage: "
        f"{rewritten_coverage:.2f}"
    )

    rewrite_accepted = (
        rewritten_coverage > initial_coverage
    )

    if rewrite_accepted:
        return {
            "original_query": query,
            "final_query": rewritten_query,
            "requeried": True,
            "rewrite_accepted": True,
            "original_coverage": initial_coverage,
            "final_coverage": rewritten_coverage,
            "results": rewritten_results,
        }

    return {
        "original_query": query,
        "final_query": query,
        "requeried": True,
        "rewrite_accepted": False,
        "original_coverage": initial_coverage,
        "final_coverage": initial_coverage,
        "results": initial_results,
    }