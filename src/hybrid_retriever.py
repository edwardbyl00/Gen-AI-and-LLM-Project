from rrf_fusion import reciprocal_rank_fusion


def hybrid_retrieve(
    bm25_results,
    dense_results,
    top_k=5,
):
    """
    Combine keyword (BM25) and dense/vector retrieval results
    using Reciprocal Rank Fusion.

    Parameters
    ----------
    bm25_results:
        Ranked BM25 results. May contain (document, score) tuples.

    dense_results:
        Ranked semantic/vector retrieval results.

    top_k:
        Number of final fused results to return.
    """

    rankings = []

    if bm25_results:
        rankings.append(bm25_results)

    if dense_results:
        rankings.append(dense_results)

    if not rankings:
        return []

    fused = reciprocal_rank_fusion(rankings)

    return fused[:top_k]