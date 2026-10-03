from .search import search_documents, filter_relevant_results
from .semantic_search import semantic_search


def hybrid_search(
    query: str,
    subject_id: int | None = None,
    limit: int = 5,
    candidate_limit: int = 20,
) -> list[dict]:

    # Keyword candidates
    fts_results = search_documents(
        query=query,
        subject_id=subject_id,
        limit=candidate_limit,
    )

    fts_results = filter_relevant_results(fts_results)

    # Semantic candidates
    semantic_results = semantic_search(
        query=query,
        subject_id=subject_id,
        limit=candidate_limit,
    )

    combined = {}

    # Reciprocal Rank Fusion.
    # k=60 is deliberately conservative so neither retrieval method
    # dominates simply because of its native scoring scale.
    k = 60

    for rank, result in enumerate(fts_results, start=1):
        chunk_id = result["chunk_id"]

        combined[chunk_id] = {
            **result,
            "fts_rank": rank,
            "semantic_rank": None,
            "semantic_score": None,
            "hybrid_score": 0.0,
        }

        combined[chunk_id]["hybrid_score"] += 1 / (k + rank)

    for rank, result in enumerate(semantic_results, start=1):
        chunk_id = result["chunk_id"]

        if chunk_id not in combined:
            combined[chunk_id] = {
                **result,
                "fts_rank": None,
                "semantic_rank": rank,
                "score": None,
                "hybrid_score": 0.0,
            }
        else:
            combined[chunk_id]["semantic_rank"] = rank
            combined[chunk_id]["semantic_score"] = result["semantic_score"]

        combined[chunk_id]["hybrid_score"] += 1 / (k + rank)

    ranked = sorted(
        combined.values(),
        key=lambda item: item["hybrid_score"],
        reverse=True,
    )

    return ranked[:limit]


def filter_hybrid_results(
    results: list[dict],
    relative_threshold: float = 0.65,
    semantic_gap_threshold: float = 0.06,
) -> list[dict]:
    """
    Remove substantially weaker retrieval results before they are
    supplied to the answering model.

    Strategy:
    - If retrieval is semantic-only, look for a meaningful drop
      between consecutive semantic scores and stop there.
    - Otherwise preserve the existing hybrid-score filtering.
    """
    if not results:
        return []

    # Semantic-only retrieval needs different filtering because RRF
    # compresses rank-only hybrid scores into a very narrow range.
    semantic_only = all(
        result.get("fts_rank") is None
        for result in results
    )

    if semantic_only:
        semantic_results = [
            result
            for result in results
            if result.get("semantic_score") is not None
        ]

        if not semantic_results:
            return results[:1]

        relevant = [semantic_results[0]]

        for previous, current in zip(
            semantic_results,
            semantic_results[1:],
        ):
            gap = (
                previous["semantic_score"]
                - current["semantic_score"]
            )

            if gap >= semantic_gap_threshold:
                break

            relevant.append(current)

        return relevant

    # Hybrid retrieval: retain results reasonably close to the best
    # fused score.
    best_score = results[0]["hybrid_score"]

    if best_score <= 0:
        return results[:1]

    relevant = [
        result
        for result in results
        if result["hybrid_score"]
        >= best_score * relative_threshold
    ]

    # Validate hybrid candidates semantically as well. This prevents
    # a generic keyword match from surviving simply because FTS gave
    # it a strong rank.
    semantic_scores = [
        result["semantic_score"]
        for result in relevant
        if result.get("semantic_score") is not None
    ]

    if semantic_scores:
        best_semantic = max(semantic_scores)

        relevant = [
            result
            for result in relevant
            if (
                result.get("semantic_score") is None
                or result["semantic_score"] >= best_semantic - 0.08
            )
        ]

    return relevant or results[:1]
