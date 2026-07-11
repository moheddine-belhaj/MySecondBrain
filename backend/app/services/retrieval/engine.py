"""RetrievalEngine — query → embed → search → fuse → deduplicate → rank → result.

Pipeline stages (hybrid mode)
------------------------------
1. Embed    : convert query to a vector via EmbeddingProvider.
2. Search   : over-fetch from Qdrant (top_k × over_fetch_factor).
3. BM25     : score all corpus chunks against the query via KeywordIndex.
4. Fuse     : weighted RRF over the two ranked lists.
5. Dedup    : remove near-duplicate chunks (heading-level, then per-note cap).
6. Trim     : keep top_k results.
7. Enrich   : assign 1-based rank numbers, build RetrievedChunk objects.

Mode selection
--------------
query.mode = "semantic"  → skip stages 3+4; sort by cosine score (original behaviour).
query.mode = "keyword"   → skip stages 1+2; sort by BM25 score.
query.mode = "hybrid"    → run all stages; fuse with weighted RRF.

KeywordIndex rebuild
--------------------
The index is built lazily on the first hybrid/keyword call, then reused.
`is_stale` is set to True by ingest/sync endpoints after they complete.
A stale index triggers a Qdrant scroll + BM25 rebuild before the search.
The rebuild runs in a thread (asyncio.to_thread) to avoid blocking the event loop.

Over-fetching
-------------
Deduplication shrinks the candidate pool. Fetching top_k × over_fetch_factor
gives the deduplicator room to discard without leaving too few results.
In hybrid mode, BM25 also fetches top_k × over_fetch_factor so there are
enough keyword candidates for meaningful RRF fusion.
"""

import asyncio
import logging
import time

from app.services.llm.base import EmbeddingProvider
from app.services.retrieval.deduplicator import Deduplicator
from app.services.retrieval.keyword_index import KeywordIndex
from app.services.retrieval.models import RetrievalQuery, RetrievalResult, RetrievedChunk
from app.services.retrieval.ranker import Ranker
from app.services.vector.models import SearchResult
from app.services.vector.repository import VectorRepository

logger = logging.getLogger("app.services.retrieval.engine")


class RetrievalEngine:
    """Stateless between calls — create once, call retrieve() as needed."""

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        qdrant: VectorRepository,
        keyword_index: KeywordIndex | None = None,
        default_top_k: int = 10,
        default_score_threshold: float = 0.0,
        default_max_chunks_per_note: int = 2,
        default_over_fetch_factor: int = 3,
    ) -> None:
        self._embedder = embedding_provider
        self._qdrant = qdrant
        self._keyword_index = keyword_index
        self._default_top_k = default_top_k
        self._default_score_threshold = default_score_threshold
        self._default_max_per_note = default_max_chunks_per_note
        self._default_over_fetch = default_over_fetch_factor

    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        """Execute the full retrieval pipeline and return a RetrievalResult.

        Never raises — any embedding or Qdrant failure propagates as-is so the
        endpoint layer can decide whether to return a 500 or a partial result.
        """
        t_start = time.monotonic()
        mode = query.mode
        filters_applied = _has_active_filters(query)
        fetch_limit = query.top_k * query.over_fetch_factor

        logger.info(
            "Retrieval: start",
            extra={
                "query": query.text[:120],
                "mode": mode,
                "top_k": query.top_k,
                "score_threshold": query.score_threshold,
                "filters_applied": filters_applied,
                "semantic_weight": query.semantic_weight,
                "keyword_weight": query.keyword_weight,
            },
        )

        semantic_candidates: list[SearchResult] = []
        keyword_candidates: list[SearchResult] = []

        # ── Stage 1+2: Embed + vector search (semantic and hybrid) ────────────
        if mode in ("semantic", "hybrid"):
            t_embed = time.monotonic()
            query_vector = await self._embedder.embed(query.text)
            embed_ms = (time.monotonic() - t_embed) * 1000
            logger.debug("Retrieval: embed", extra={"embed_ms": round(embed_ms, 1)})

            semantic_candidates = await self._qdrant.search(
                query_vector=query_vector,
                limit=fetch_limit,
                score_threshold=query.score_threshold,
                filters=query.filters,
            )
            logger.debug(
                "Retrieval: semantic candidates",
                extra={
                    "count": len(semantic_candidates),
                    "top": round(semantic_candidates[0].score, 4) if semantic_candidates else None,
                },
            )

        # ── Stage 3: BM25 keyword search (keyword and hybrid) ────────────────
        if mode in ("keyword", "hybrid"):
            await self._ensure_keyword_index_built()
            if self._keyword_index is not None:
                keyword_candidates = self._keyword_index.search(query.text, limit=fetch_limit)
                logger.debug(
                    "Retrieval: keyword candidates",
                    extra={"count": len(keyword_candidates)},
                )

        # ── Stage 4: Fusion ───────────────────────────────────────────────────
        if mode == "semantic":
            ranked = Ranker.sort_by_score(semantic_candidates)
        elif mode == "keyword":
            ranked = Ranker.sort_by_score(keyword_candidates)
        else:  # hybrid
            ranked = Ranker.weighted_rrf_fuse(
                [
                    (semantic_candidates, query.semantic_weight),
                    (keyword_candidates, query.keyword_weight),
                ],
                rrf_k=query.rrf_k,
            )

        total_candidates = len(ranked)
        logger.debug("Retrieval: fused", extra={"total": total_candidates, "mode": mode})

        # ── Stage 5: Deduplicate ──────────────────────────────────────────────
        dedup_removed = 0
        if query.deduplicate and ranked:
            deduplicator = Deduplicator(max_per_note=query.max_chunks_per_note)
            ranked, dedup_removed = deduplicator.deduplicate(ranked)
            logger.debug("Retrieval: dedup", extra={"removed": dedup_removed})

        # ── Stage 6: Trim to top_k ────────────────────────────────────────────
        final = ranked[: query.top_k]

        # ── Stage 7: Enrich with rank numbers ────────────────────────────────
        chunks = [_to_retrieved_chunk(r, rank=i + 1) for i, r in enumerate(final)]

        latency_ms = round((time.monotonic() - t_start) * 1000, 1)
        logger.info(
            "Retrieval: complete",
            extra={
                "mode": mode,
                "results": len(chunks),
                "total_candidates": total_candidates,
                "keyword_candidates": len(keyword_candidates),
                "dedup_removed": dedup_removed,
                "latency_ms": latency_ms,
                "top_score": round(chunks[0].score, 4) if chunks else None,
            },
        )

        return RetrievalResult(
            query=query.text,
            chunks=chunks,
            total_candidates=total_candidates,
            deduplicated_count=dedup_removed,
            latency_ms=latency_ms,
            score_threshold=query.score_threshold,
            filters_applied=filters_applied,
            retrieval_mode=mode,
            keyword_candidates=len(keyword_candidates),
        )

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _ensure_keyword_index_built(self) -> None:
        """Build (or rebuild) the BM25 index if stale. No-op if no index provided."""
        if self._keyword_index is None or not self._keyword_index.is_stale:
            return
        logger.info(
            "KeywordIndex: rebuilding from Qdrant scroll",
            extra={"corpus_size_before": self._keyword_index.corpus_size},
        )
        entries = await self._qdrant.scroll_all_chunks()
        await asyncio.to_thread(self._keyword_index.build, entries)
        logger.info(
            "KeywordIndex: rebuild complete",
            extra={"corpus_size": self._keyword_index.corpus_size},
        )


# ── Module-level helpers ───────────────────────────────────────────────────────


def _has_active_filters(query: RetrievalQuery) -> bool:
    if query.filters is None:
        return False
    f = query.filters
    return bool(f.tags or f.note_id or f.note_path or f.note_title)


def _to_retrieved_chunk(result: SearchResult, rank: int) -> RetrievedChunk:
    p = result.payload
    return RetrievedChunk(
        chunk_id=result.chunk_id,
        score=result.score,
        rank=rank,
        chunk_text=result.chunk_text,
        note_title=p.get("note_title", ""),
        note_path=p.get("note_path", ""),
        note_id=p.get("note_id", ""),
        tags=p.get("tags", []),
        heading_path=p.get("heading_path", []),
        chunk_index=p.get("chunk_index", 0),
        total_chunks=p.get("total_chunks", 0),
        word_count=p.get("word_count", 0),
        indexed_at=p.get("indexed_at", ""),
        note_modified_at=p.get("note_modified_at", ""),
    )
