"""RetrievalEngine — query → embed → search → deduplicate → rank → result.

Pipeline stages
---------------
1. Embed   : convert the raw query string into a vector via EmbeddingProvider.
2. Search  : over-fetch (top_k × over_fetch_factor) from Qdrant with optional
             metadata filters and score threshold.
3. Rank    : re-sort by cosine score (Qdrant already returns sorted, but
             explicit sort makes the pipeline robust to future hybrid fusion).
4. Dedup   : remove near-duplicate chunks (heading-level, then per-note cap).
5. Trim    : keep only the top_k results.
6. Enrich  : assign 1-based rank numbers and build RetrievedChunk objects.

Over-fetching
-------------
Deduplication shrinks the candidate pool. If we fetched exactly top_k and then
removed duplicates we might return fewer than top_k results. By fetching
top_k × over_fetch_factor we give the deduplicator room to discard chunks
while still filling the requested top_k.

Observability
-------------
Every stage is logged at DEBUG level with timing and counts. The final INFO
log line summarises the full run: results, candidates, dedup removed, latency.
"""

import logging
import time

from app.services.llm.base import EmbeddingProvider
from app.services.retrieval.deduplicator import Deduplicator
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
        default_top_k: int = 10,
        default_score_threshold: float = 0.0,
        default_max_chunks_per_note: int = 2,
        default_over_fetch_factor: int = 3,
    ) -> None:
        self._embedder = embedding_provider
        self._qdrant = qdrant
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

        filters_applied = _has_active_filters(query)

        logger.info(
            "Retrieval: start",
            extra={
                "query": query.text[:120],
                "top_k": query.top_k,
                "score_threshold": query.score_threshold,
                "filters_applied": filters_applied,
                "deduplicate": query.deduplicate,
                "max_chunks_per_note": query.max_chunks_per_note,
                "over_fetch_factor": query.over_fetch_factor,
            },
        )

        # ── Stage 1: Embed ─────────────────────────────────────────────────────
        t_embed = time.monotonic()
        query_vector = await self._embedder.embed(query.text)
        embed_ms = (time.monotonic() - t_embed) * 1000
        logger.debug("Retrieval: embed", extra={"embed_ms": round(embed_ms, 1), "dim": len(query_vector)})

        # ── Stage 2: Over-fetch from Qdrant ────────────────────────────────────
        fetch_limit = query.top_k * query.over_fetch_factor
        candidates: list[SearchResult] = await self._qdrant.search(
            query_vector=query_vector,
            limit=fetch_limit,
            score_threshold=query.score_threshold,
            filters=query.filters,
        )
        total_candidates = len(candidates)
        logger.debug(
            "Retrieval: candidates",
            extra={
                "fetched": total_candidates,
                "fetch_limit": fetch_limit,
                "top_score": round(candidates[0].score, 4) if candidates else None,
                "min_score": round(candidates[-1].score, 4) if candidates else None,
            },
        )

        # ── Stage 3: Rank ──────────────────────────────────────────────────────
        ranked = Ranker.sort_by_score(candidates)

        # ── Stage 4: Deduplicate ───────────────────────────────────────────────
        dedup_removed = 0
        if query.deduplicate and ranked:
            deduplicator = Deduplicator(max_per_note=query.max_chunks_per_note)
            ranked, dedup_removed = deduplicator.deduplicate(ranked)
            logger.debug(
                "Retrieval: dedup",
                extra={"removed": dedup_removed, "remaining": len(ranked)},
            )

        # ── Stage 5: Trim to top_k ─────────────────────────────────────────────
        final = ranked[: query.top_k]

        # ── Stage 6: Enrich with rank numbers ─────────────────────────────────
        chunks = [_to_retrieved_chunk(r, rank=i + 1) for i, r in enumerate(final)]

        latency_ms = round((time.monotonic() - t_start) * 1000, 1)
        logger.info(
            "Retrieval: complete",
            extra={
                "results": len(chunks),
                "total_candidates": total_candidates,
                "dedup_removed": dedup_removed,
                "latency_ms": latency_ms,
                "top_score": round(chunks[0].score, 4) if chunks else None,
                "bottom_score": round(chunks[-1].score, 4) if chunks else None,
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
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


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
