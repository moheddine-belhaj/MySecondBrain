"""Ranker — orders retrieval candidates by relevance.

Current implementation: pure vector (cosine) score sort.
The class is structured to support Reciprocal Rank Fusion (RRF) for hybrid
search (dense vector + sparse BM25) without changing the engine interface.

How to add hybrid search later
--------------------------------
1. Add a BM25 index (e.g. via tantivy-py or a lightweight inverted index).
2. Get keyword ranks alongside vector ranks.
3. Replace `sort_by_score()` with `rrf_fuse(vector_ranks, bm25_ranks)`.

RRF formula
-----------
    score(d) = Σ_i  1 / (k + rank_i(d))

where k=60 dampens the influence of top ranks (standard Cormack et al. value).
Each ranking system i contributes a score; the sum is the fused rank order.
Documents not in a ranking get a rank of len(results)+1 (worst possible).
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
    ) -> list[SearchResult]:
        """Reciprocal Rank Fusion across multiple ranked lists.

        Each list is an independent ranking of the same candidates (e.g. one
        from vector search, one from BM25). The fused list orders candidates by
        their summed RRF score — higher is better.

        Candidates that appear in only some lists are still included; they
        receive a rank of len(list)+1 for each list they are absent from.
        """
        rrf_scores: dict[str, float] = {}
        all_results: dict[str, SearchResult] = {}

        for ranked in ranked_lists:
            n = len(ranked)
            for rank_idx, result in enumerate(ranked):
                cid = result.chunk_id
                all_results[cid] = result
                rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank_idx + 1)

            # penalise candidates absent from this list
            for cid in all_results:
                if cid not in {r.chunk_id for r in ranked}:
                    rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (_RRF_K + n + 1)

        return sorted(all_results.values(), key=lambda r: rrf_scores[r.chunk_id], reverse=True)
