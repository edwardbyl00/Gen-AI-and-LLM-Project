from retrieval import (
    load_policies,
    search_with_requery,
)

def retrieve_policy_evidence(
    question,
    query_date=None,
    top_k=3,
    policies=None
):
    """
    Retrieve policy evidence for a user question.

    Returns a clean package that other agents can use.
    """

    if policies is None:
        policies = load_policies()

    output = search_with_requery(
        query=question,
        policies=policies,
        query_date=query_date,
        top_k=top_k
    )

    evidence = []

    for policy, score in output["results"]:
        evidence.append(
            {
                "document_id": policy.get("document_id"),
                "chunk_id": policy.get("chunk_id"),
                "title": policy.get("title"),
                "source": policy.get("source"),
                "category": policy.get("category") or policy.get("document_type"),
                "url": policy.get("url") or policy.get("source_url"),
                "effective_date": policy.get("effective_date"),
                "text": policy.get("text") or policy.get("content"),
                "section_title": policy.get("section_title"),
                "section_path": policy.get("section_path"),
                "score": round(float(score), 3),
            }
)

    return {
        "question": question,
        "query_date": query_date,
        "final_query": output["final_query"],
        "requeried": output["requeried"],
        "rewrite_accepted": output["rewrite_accepted"],
        "original_coverage": output.get("original_coverage", 0.0),
        "final_coverage": output.get("final_coverage", 0.0),
        "evidence": evidence,
    }


if __name__ == "__main__":
    result = retrieve_policy_evidence(
        question="Can I use OA savings for my flat?",
        query_date="2026-06-01",
        top_k=3
    )

    print("\nFinal query:", result["final_query"])
    print("Re-query used:", result["requeried"])
    print()

    for item in result["evidence"]:
        print(
            item["document_id"],
            "|",
            item["title"],
            "|",
            item["score"]
        )