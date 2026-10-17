from hybrid_search import load_policies, bm25_search


def should_requery(results, min_score=0.5):
    """
    Decide whether the first retrieval looks too weak.
    """

    if not results:
        return True

    top_score = float(results[0][1])

    return top_score < min_score


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
    top_k=3,
    min_score=0.5
):
    """
    Search once.

    If retrieval looks weak, rewrite the query and search again.
    """

    first_results = bm25_search(
        query=query,
        policies=policies,
        query_date=query_date,
        top_k=top_k
    )

    if not should_requery(first_results, min_score):
        return {
            "original_query": query,
            "final_query": query,
            "requeried": False,
            "results": first_results
        }

    rewritten_query = rewrite_query(query)

    second_results = bm25_search(
        query=rewritten_query,
        policies=policies,
        query_date=query_date,
        top_k=top_k
    )

    return {
        "original_query": query,
        "final_query": rewritten_query,
        "requeried": True,
        "results": second_results
    }


if __name__ == "__main__":
    policies = load_policies()

    # Deliberately use "OA" so we can test query rewriting
    query = "Can I use OA savings for my flat?"

    output = search_with_requery(
        query=query,
        policies=policies,
        query_date="2026-06-01",
        top_k=3,
        min_score=2.0
    )

    print("\nOriginal query:", output["original_query"])
    print("Final query:", output["final_query"])
    print("Re-query used:", output["requeried"])
    print()

    for policy, score in output["results"]:
        print(
            policy["document_id"],
            "|",
            policy["title"],
            "| score:",
            round(float(score), 3)
        )