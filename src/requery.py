from hybrid_search import load_policies, bm25_search, tokenize

STOPWORDS = {
    "a", "an", "the", "i", "my", "me",
    "can", "could", "do", "does", "is", "are",
    "to", "for", "of", "in", "on", "with",
    "use", "using"
}

def get_meaningful_tokens(text):
    """
    Remove common words so we focus on important query terms.
    """
    return {
        token
        for token in tokenize(text)
        if token not in STOPWORDS
    }

def get_query_coverage(results, query):
    """
    Measure how many important query terms appear
    in the top retrieved document.
    """

    if not results:
        return 0.0

    top_policy, _ = results[0]

    query_tokens = get_meaningful_tokens(query)

    if not query_tokens:
        return 1.0

    top_text = (
        f"{top_policy['title']} "
        f"{top_policy['category']} "
        f"{top_policy['text']}"
    )

    document_tokens = get_meaningful_tokens(top_text)

    matched_tokens = query_tokens.intersection(document_tokens)

    return len(matched_tokens) / len(query_tokens)


def should_requery(results, query, min_coverage=0.5):
    """
    Re-query when retrieval is missing or weak.
    """

    if not results:
        return True

    top_score = float(results[0][1])

    if top_score <= 0:
        return True

    coverage = get_query_coverage(results, query)

    print(f"Initial query coverage: {coverage:.2f}")

    return coverage < min_coverage


def rewrite_query(query):
    """
    Simple rule-based query expansion for development/testing.

    Later this can be replaced by an LLM query rewriter.
    """

    replacements = {
        "OA": "Ordinary Account",
        "MOP": "Minimum Occupation Period",
        "EHG": "Enhanced CPF Housing Grant",
    }

    rewritten = query

    for short_form, full_form in replacements.items():
        rewritten = rewritten.replace(short_form, full_form)

    return rewritten


def search_with_requery(
    query,
    policies,
    query_date=None,
    top_k=3
):
    """
    Search once.

    If retrieval looks weak:
    1. rewrite the query;
    2. search again;
    3. keep the rewritten results only if they improve retrieval.
    """

    first_results = bm25_search(
        query=query,
        policies=policies,
        query_date=query_date,
        top_k=top_k
    )

    first_coverage = get_query_coverage(
        first_results,
        query
    )

    if not should_requery(
        first_results,
        query=query,
        min_coverage=0.5
    ):
        return {
            "original_query": query,
            "final_query": query,
            "requeried": False,
            "rewrite_accepted": False,
            "original_coverage": first_coverage,
            "final_coverage": first_coverage,
            "results": first_results
        }

    rewritten_query = rewrite_query(query)

    second_results = bm25_search(
        query=rewritten_query,
        policies=policies,
        query_date=query_date,
        top_k=top_k
    )

    second_coverage = get_query_coverage(
        second_results,
        rewritten_query
    )

    print(f"Rewritten query coverage: {second_coverage:.2f}")

    # Accept rewrite only if retrieval improves
    if second_coverage > first_coverage:
        return {
            "original_query": query,
            "final_query": rewritten_query,
            "requeried": True,
            "rewrite_accepted": True,
            "original_coverage": first_coverage,
            "final_coverage": second_coverage,
            "results": second_results
        }

    return {
        "original_query": query,
        "final_query": query,
        "requeried": True,
        "rewrite_accepted": False,
        "original_coverage": first_coverage,
        "final_coverage": first_coverage,
        "results": first_results
    }


if __name__ == "__main__":
    policies = load_policies()

    # Deliberately use "OA" so we can test query rewriting
    query = "Can I use OA savings for my flat?"

    output = search_with_requery(
        query=query,
        policies=policies,
        query_date="2026-06-01",
        top_k=3
    )

    print("\nOriginal query:", output["original_query"])
    print("Final query:", output["final_query"])
    print("Re-query attempted:", output["requeried"])
    print("Rewrite accepted:", output["rewrite_accepted"])
    print(
        "Coverage:",
        round(output["original_coverage"], 2),
        "→",
        round(output["final_coverage"], 2)
    )
    print()

    for policy, score in output["results"]:
        print(
            policy["document_id"],
            "|",
            policy["title"],
            "| score:",
            round(float(score), 3)
        )