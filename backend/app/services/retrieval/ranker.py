"""Ranker — orders retrieval candidates by relevance.

Three strategies are available:

sort_by_score()
    Pure cosine-similarity sort. Used for semantic-only retrieval.

rrf_fuse(*ranked_lists)
    Reciprocal Rank Fusion — equal weight per list. Kept for backwards
    compatibility and single-caller convenience.

weighted_rrf_fuse(ranked_lists)
    Weighted RRF — each list carries an explicit float weight.
    Used for hybrid (semantic + BM25) retrieval.

RRF formula
-----------
    score(d) = Σ_i  weight_i / (k + rank_i(d))

where k=60 dampens the influence of top ranks (Cormack et al. 2009).
Candidates absent from a list receive the worst-rank penalty:
    weight_i / (k + len(list_i) + 1)

Why RRF over linear combination?
---------------------------------
Cosine scores (0–1) and BM25 scores (0–∞) live on incompatible scales.
Normalising them introduces a free parameter and is sensitive to outliers.
RRF only uses ranks, so score scale is irrelevant — the fused order is
robust and consistent regardless of the individual scoring functions.
"""

from app.services.vector.models import SearchResult

_RRF_K = 60


class Ranker:
    @staticmethod
    def sort_by_score(results: list[SearchResult]) -> list[SearchResult]:
        """Sort candidates by cosine similarity descending. Stable — ties keep Qdrant order."""
        return sorted(results, key=lambda r: r.score, reverse=True)

    @staticmethod
    def rrf_fuse(
        *ranked_lists: list[SearchResult],
        rrf_k: int = _RRF_K,
    ) -> list[SearchResult]:
        """Reciprocal Rank Fusion across multiple ranked lists (equal weights).

        Delegates to weighted_rrf_fuse with weight=1.0 per list.
        """
        return Ranker.weighted_rrf_fuse(
            [(ranked, 1.0) for ranked in ranked_lists],
            rrf_k=rrf_k,
        )

    @staticmethod
    def weighted_rrf_fuse(
        ranked_lists: list[tuple[list[SearchResult], float]],
        rrf_k: int = _RRF_K,
    ) -> list[SearchResult]:
        """Reciprocal Rank Fusion with per-list weights.

        Each entry in `ranked_lists` is `(results, weight)`.
        Higher weight → that list has more influence on the final order.

        Example — favour semantic search 70 / BM25 30:
            Ranker.weighted_rrf_fuse(
                [(semantic_results, 0.7), (bm25_results, 0.3)]
            )

        The returned SearchResult objects carry the fused RRF score in
        their `.score` field (not the original cosine or BM25 score).
        """
        rrf_scores: dict[str, float] = {}
        all_results: dict[str, SearchResult] = {}

        for ranked, weight in ranked_lists:
            n = len(ranked)
            present: set[str] = set()

            for rank_idx, result in enumerate(ranked):
                cid = result.chunk_id
                all_results[cid] = result
                present.add(cid)
                rrf_scores[cid] = rrf_scores.get(cid, 0.0) + weight / (rrf_k + rank_idx + 1)

            # Penalise candidates absent from this list.
            for cid in all_results:
                if cid not in present:
                    rrf_scores[cid] = rrf_scores.get(cid, 0.0) + weight / (rrf_k + n + 1)

        # Return new SearchResult objects whose .score IS the RRF score so
        # downstream sort_by_score / deduplicator work without modification.
        return sorted(
            [
                SearchResult(
                    chunk_id=r.chunk_id,
                    score=rrf_scores[r.chunk_id],
                    chunk_text=r.chunk_text,
                    payload=r.payload,
                )
                for r in all_results.values()
            ],
            key=lambda r: r.score,
            reverse=True,
        )
