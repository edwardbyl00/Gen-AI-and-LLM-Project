def _extract_item(result):
    """
    Support either dictionaries or (dictionary, score) tuples.
    """

    if isinstance(result, tuple):
        return result[0]

    return result


def _result_key(result):
    """
    Prefer chunk_id for real P4 chunks.
    Fall back to document_id for mock data.
    """

    item = _extract_item(result)

    return (
        item.get("chunk_id")
        or item.get("document_id")
    )


def reciprocal_rank_fusion(rankings, k=60, weights=None):
    """
    Fuse ranked result lists using weighted Reciprocal Rank Fusion.

    Weighted RRF score:
        sum(weight / (k + rank))

    If weights are not provided, all rankings receive equal weight.
    """
    if weights is None:
        weights = [1.0] * len(rankings)

    if len(weights) != len(rankings):
        raise ValueError("weights must match number of rankings")

    fused_scores = {}
    items = {}

    for ranking, weight in zip(rankings, weights):
        for rank, result in enumerate(
            ranking,
            start=1,
        ):
            key = _result_key(result)

            if key is None:
                continue

            item = _extract_item(result)
            items[key] = item

            fused_scores[key] = (
                fused_scores.get(key, 0.0)
                + weight / (k + rank)
            )

    ordered_keys = sorted(
        fused_scores,
        key=fused_scores.get,
        reverse=True,
    )

    fused_results = []

    for key in ordered_keys:
        result = dict(items[key])
        result["rrf_score"] = fused_scores[key]
        fused_results.append(result)

    return fused_results


def hybrid_retrieve(
    bm25_results,
    dense_results,
    top_k=5,
    bm25_weight=1.0,
    dense_weight=1.0,
):
    """
    Combine BM25 and dense/vector retrieval rankings
    using weighted Reciprocal Rank Fusion.
    """
    rankings = []
    weights = []

    if bm25_results:
        rankings.append(bm25_results)
        weights.append(bm25_weight)

    if dense_results:
        rankings.append(dense_results)
        weights.append(dense_weight)

    if not rankings:
        return []

    fused = reciprocal_rank_fusion(
        rankings,
        weights=weights,
    )

    return fused[:top_k]