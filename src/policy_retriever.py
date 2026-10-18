from hybrid_retriever import hybrid_retrieve
from retrieval import (
    load_policies,
    search_with_requery,
    get_meaningful_tokens,
)
from date_utils import (
    filter_by_effective_date,
    select_latest_versions,
)
from pathlib import Path

from chunk_adapter import load_chunks_jsonl


def _policy_text(policy):
    return " ".join(
        [
            policy.get("title") or "",
            policy.get("category")
            or policy.get("document_type")
            or "",
            policy.get("text")
            or policy.get("content")
            or "",
        ]
    )


def _coverage_for_policy(query, policy):
    query_tokens = get_meaningful_tokens(query)

    if not query_tokens:
        return 1.0

    policy_tokens = get_meaningful_tokens(
        _policy_text(policy)
    )

    matched = query_tokens.intersection(
        policy_tokens
    )

    return len(matched) / len(query_tokens)


def _build_evidence(policy, score):
    return {
        "document_id": policy.get("document_id"),
        "chunk_id": policy.get("chunk_id"),
        "title": policy.get("title"),
        "source": policy.get("source"),
        "category": (
            policy.get("category")
            or policy.get("document_type")
        ),
        "url": (
            policy.get("url")
            or policy.get("source_url")
        ),
        "effective_date": policy.get(
            "effective_date"
        ),
        "text": (
            policy.get("text")
            or policy.get("content")
        ),
        "section_title": policy.get(
            "section_title"
        ),
        "section_path": policy.get(
            "section_path"
        ),
        "score": round(float(score), 6),
    }


def retrieve_policy_evidence(
    question,
    query_date=None,
    top_k=3,
    policies=None,
    dense_results=None,
    use_dense=False,
):
    """
    Retrieve policy evidence.

    Without dense_results:
        BM25 + date awareness + re-query.

    With dense_results:
        BM25 + dense retrieval fused using RRF.
    """

    if policies is None:
        if use_dense:
            policies = load_chunks_jsonl(
                Path("data/processed/chunks.jsonl")
            )
        else:
            policies = load_policies()

    output = search_with_requery(
        query=question,
        policies=policies,
        query_date=query_date,
        top_k=top_k,
    )

    if dense_results is None and use_dense:
        from dense_retriever import dense_retrieve

        dense_results = dense_retrieve(
            output["final_query"],
            top_k=top_k,
        )

    # --------------------------------------------------
    # Hybrid path
    # --------------------------------------------------

    if dense_results:
        dense_documents = []

        for item in dense_results:
            if isinstance(item, tuple):
                dense_documents.append(item[0])
            else:
                dense_documents.append(item)

        if query_date:
            dense_documents = (
                filter_by_effective_date(
                    dense_documents,
                    query_date,
                )
            )

            dense_documents = (
                select_latest_versions(
                    dense_documents
                )
            )

        fused_results = hybrid_retrieve(
            bm25_results=output["results"],
            dense_results=dense_documents,
            top_k=top_k,
        )

        evidence = [
            _build_evidence(
                policy,
                policy.get("rrf_score", 0.0),
            )
            for policy in fused_results
        ]

        final_coverage = 0.0

        if fused_results:
            final_coverage = (
                _coverage_for_policy(
                    output["final_query"],
                    fused_results[0],
                )
            )

        return {
            "question": question,
            "query_date": query_date,
            "retrieval_mode": "hybrid",
            "final_query": output["final_query"],
            "requeried": output["requeried"],
            "rewrite_accepted": (
                output["rewrite_accepted"]
            ),
            "original_coverage": output.get(
                "original_coverage",
                0.0,
            ),
            "final_coverage": final_coverage,
            "evidence": evidence,
        }

    # --------------------------------------------------
    # BM25-only path
    # --------------------------------------------------

    evidence = []

    for policy, score in output["results"]:
        evidence.append(
            _build_evidence(
                policy,
                score,
            )
        )

    return {
        "question": question,
        "query_date": query_date,
        "retrieval_mode": "bm25",
        "final_query": output["final_query"],
        "requeried": output["requeried"],
        "rewrite_accepted": (
            output["rewrite_accepted"]
        ),
        "original_coverage": output.get(
            "original_coverage",
            0.0,
        ),
        "final_coverage": output.get(
            "final_coverage",
            0.0,
        ),
        "evidence": evidence,
    }