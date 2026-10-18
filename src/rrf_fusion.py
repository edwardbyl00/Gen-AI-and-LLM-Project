def _extract_item(result):
    """
    Support either:
    - result dictionaries
    - (dictionary, score) tuples from BM25
    """
    if isinstance(result, tuple):
        return result[0]

    return result


def _result_key(result):
    """
    Prefer chunk_id when available because P4 retrieval is chunk-based.
    Fall back to document_id for mock data.
    """
    item = _extract_item(result)

    return (
        item.get("chunk_id")
        or item.get("document_id")
    )


def reciprocal_rank_fusion(rankings, k=60):
    """
    Fuse multiple ranked result lists using Reciprocal Rank Fusion.

    RRF score:
        sum(1 / (k + rank))

    Higher score = stronger combined ranking.
    """

    fused_scores = {}
    items = {}

    for ranking in rankings:
        for rank, result in enumerate(ranking, start=1):
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
        reverse=True
    )

    fused_results = []

    for key in ordered_keys:
        result = dict(items[key])
        result["rrf_score"] = fused_scores[key]
        fused_results.append(result)

    return fused_results