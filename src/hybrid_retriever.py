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


def reciprocal_rank_fusion(rankings, k=60):
    """
    Fuse ranked result lists using Reciprocal Rank Fusion.

    RRF score:
        sum(1 / (k + rank))
    """

    fused_scores = {}
    items = {}

    for ranking in rankings:
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
                + 1 / (k + rank)
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
):
    """
    Combine BM25 and dense/vector retrieval rankings
    using Reciprocal Rank Fusion.
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