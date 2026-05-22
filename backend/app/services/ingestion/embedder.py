"""EmbeddingPipeline — orchestrates scan → chunk → embed → index.

Pipeline stages
---------------
1. Scan   : VaultScanner reads markdown files and produces VaultNote objects.
2. Chunk  : MarkdownChunker splits each note into TextChunk objects.
3. Embed  : OllamaService.embed_batch() converts chunk texts into vectors.
            Chunks are grouped into configurable batches to limit round-trips.
4. Index  : QdrantService.upsert() stores (vector, payload) pairs.
5. Prune  : Stale point IDs (chunks from deleted/re-chunked notes) are deleted.

Batching
--------
All chunks across all notes are collected into a flat list, then sliced into
batches of `batch_size`. Each batch is a single HTTP call to Ollama. This
amortises connection overhead and is more efficient than one call per chunk.

If a batch fails, it is logged and skipped — the pipeline continues with
the remaining batches. Partial indexing is better than a full abort.

Stale-chunk cleanup
-------------------
Before the run, we fetch all existing point IDs from Qdrant. After upserting
the new vectors, we compute the set difference:

    stale = existing_ids − new_chunk_ids

Any ID in `stale` belongs to a chunk that no longer exists in the vault
(because the note was deleted or its content hash changed). We delete these.

This makes repeated runs idempotent: the collection always reflects the current
state of the vault after a successful run.

Metrics
-------
`IndexingStats` is a simple dataclass accumulating counters. It is returned
from `run()` and translated into the `IngestStatus` API response model.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.services.ingestion.chunker import MarkdownChunker
from app.services.ingestion.models import TextChunk
from app.services.llm.base import EmbeddingProvider
from app.services.vault.models import ScanResult, VaultNote
from app.services.vault.scanner import VaultScanner
from app.services.vector.client import QdrantService
from app.services.vector.models import VectorPayload

logger = logging.getLogger("app.services.ingestion.embedder")


@dataclass
class IndexingStats:
    """Counters accumulated during one pipeline run."""

    total_notes: int = 0
    processed_notes: int = 0
    total_chunks: int = 0
    embedded_chunks: int = 0
    indexed_chunks: int = 0
    deleted_stale_chunks: int = 0
    duration_ms: float = 0.0
    errors: list[str] = field(default_factory=list)


class EmbeddingPipeline:
    """Orchestrates the full ingest pipeline for an Obsidian vault.

    Stateless between runs — create once, call `run()` as many times as needed.
    All state is local to the `run()` invocation.
    """

    def __init__(
        self,
        scanner: VaultScanner,
        chunker: MarkdownChunker,
        embedding_provider: EmbeddingProvider,
        qdrant: QdrantService,
        batch_size: int = 32,
    ) -> None:
        self._scanner = scanner
        self._chunker = chunker
        self._embedder = embedding_provider
        self._qdrant = qdrant
        self._batch_size = batch_size

    # ── Public API ─────────────────────────────────────────────────────────────

    async def run(self) -> IndexingStats:
        """Execute the full pipeline and return accumulated stats.

        Never raises — all per-batch errors are captured in `stats.errors`.
        The caller decides whether a partial result is acceptable.
        """
        stats = IndexingStats()
        t_start = time.monotonic()

        # ── Stage 1: Ensure collection exists ─────────────────────────────────
        await self._qdrant.ensure_collection()

        # ── Stage 2: Scan ──────────────────────────────────────────────────────
        logger.info("Pipeline: scanning vault")
        scan_result: ScanResult = await self._scanner.scan()
        stats.total_notes = len(scan_result.notes)
        logger.info("Pipeline: scan complete", extra={"notes": stats.total_notes})

        if not scan_result.notes:
            stats.duration_ms = _elapsed_ms(t_start)
            return stats

        # ── Stage 3: Chunk ─────────────────────────────────────────────────────
        logger.info("Pipeline: chunking notes")
        note_lookup: dict[str, VaultNote] = {n.content_hash: n for n in scan_result.notes}
        chunk_results = self._chunker.chunk_notes(scan_result.notes)
        stats.processed_notes = len(chunk_results)

        all_chunks: list[TextChunk] = []
        for cr in chunk_results:
            all_chunks.extend(cr.chunks)
        stats.total_chunks = len(all_chunks)
        logger.info("Pipeline: chunking complete", extra={"chunks": stats.total_chunks})

        # ── Stage 4: Fetch existing IDs for stale-chunk detection ─────────────
        existing_ids: set[str] = await self._qdrant.get_all_point_ids()
        new_ids: set[str] = {c.id for c in all_chunks}

        # ── Stage 5: Embed + index in batches ─────────────────────────────────
        now_iso = datetime.now(timezone.utc).isoformat()

        for i in range(0, len(all_chunks), self._batch_size):
            batch = all_chunks[i : i + self._batch_size]
            await self._embed_and_index_batch(batch, note_lookup, now_iso, stats)

        # ── Stage 6: Delete stale chunks ──────────────────────────────────────
        stale_ids = list(existing_ids - new_ids)
        if stale_ids:
            try:
                await self._qdrant.delete_points(stale_ids)
                stats.deleted_stale_chunks = len(stale_ids)
            except Exception as exc:
                msg = f"Failed to delete stale points: {exc}"
                logger.error(msg)
                stats.errors.append(msg)

        stats.duration_ms = _elapsed_ms(t_start)
        logger.info(
            "Pipeline: complete",
            extra={
                "embedded": stats.embedded_chunks,
                "indexed": stats.indexed_chunks,
                "stale_deleted": stats.deleted_stale_chunks,
                "duration_ms": round(stats.duration_ms, 1),
                "errors": len(stats.errors),
            },
        )
        return stats

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _embed_and_index_batch(
        self,
        batch: list[TextChunk],
        note_lookup: dict[str, VaultNote],
        indexed_at: str,
        stats: IndexingStats,
    ) -> None:
        texts = [chunk.text for chunk in batch]
        try:
            vectors = await self._embedder.embed_batch(texts)
            stats.embedded_chunks += len(vectors)
        except Exception as exc:
            msg = f"Embedding batch failed (chunks {batch[0].id}…): {exc}"
            logger.warning(msg, extra={"batch_size": len(batch)})
            stats.errors.append(msg)
            return  # skip indexing this batch

        payloads = [
            _build_payload(chunk, note_lookup, indexed_at) for chunk in batch
        ]

        try:
            await self._qdrant.upsert(payloads, vectors)
            stats.indexed_chunks += len(payloads)
        except Exception as exc:
            msg = f"Qdrant upsert failed (batch starting {batch[0].id}): {exc}"
            logger.error(msg, extra={"batch_size": len(batch)})
            stats.errors.append(msg)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_payload(
    chunk: TextChunk,
    note_lookup: dict[str, VaultNote],
    indexed_at: str,
) -> VectorPayload:
    note = note_lookup.get(chunk.metadata.note_id)
    note_modified_at = note.modified_at.isoformat() if note else indexed_at

    return VectorPayload(
        chunk_id=chunk.id,
        note_id=chunk.metadata.note_id,
        note_title=chunk.metadata.note_title,
        note_path=chunk.metadata.note_path,
        tags=list(chunk.metadata.tags),
        heading_path=list(chunk.metadata.heading_path),
        chunk_index=chunk.metadata.chunk_index,
        total_chunks=chunk.metadata.total_chunks,
        word_count=chunk.word_count,
        indexed_at=indexed_at,
        note_modified_at=note_modified_at,
    )


def _elapsed_ms(t_start: float) -> float:
    return round((time.monotonic() - t_start) * 1000, 1)
