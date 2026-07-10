"""IncrementalSyncEngine — syncs only changed vault content to Qdrant.

Algorithm
---------
1. Scan vault  → current_state  = {path: sha256}
2. Load store  → persisted_state = {path: sha256}
3. Diff:
   new_paths      = current − persisted          (embed + index)
   deleted_paths  = persisted − current          (delete from Qdrant)
   modified_paths = common where hash differs    (delete old + embed new)
   unchanged      = common where hash matches    (skip entirely)
4. Process deletes first (idempotent), then embeds.
5. Save updated state to disk.

Hashing strategy
----------------
SHA-256 of raw file bytes (computed by VaultScanner._parse_file). Using raw
bytes means hash changes whenever content, encoding, or line endings change —
reliable detection with no false negatives.

State persistence
-----------------
IndexStateStore writes {path: hash} as JSON. A crash between "embed success"
and "save state" means those notes will be re-indexed on the next run
(duplicate upsert — harmless because upsert is idempotent). A crash before
"embed" means the note is simply processed again next run. Both failure modes
converge to a consistent state.

Scheduling
----------
If settings.sync_interval_minutes > 0, main.py creates an asyncio task that
calls sync() on that interval. The engine is stateless between runs (no locks,
no in-process cache) so concurrent calls from the scheduler and a manual API
call are safe — the second caller simply sees the result of the first call's
state file.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.services.ingestion.chunker import MarkdownChunker
from app.services.ingestion.models import TextChunk
from app.services.indexing.state_store import IndexStateStore
from app.services.llm.base import EmbeddingProvider
from app.services.vault.models import VaultNote
from app.services.vault.scanner import VaultScanner
from app.services.vector.models import VectorPayload
from app.services.vector.repository import VectorRepository

logger = logging.getLogger("app.services.indexing.sync_engine")


@dataclass
class SyncStats:
    """Counters from one incremental sync run."""

    new_notes: int = 0
    modified_notes: int = 0
    deleted_notes: int = 0
    unchanged_notes: int = 0
    new_chunks: int = 0
    duration_ms: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return self.new_notes > 0 or self.modified_notes > 0 or self.deleted_notes > 0


class IncrementalSyncEngine:
    """Synchronizes only changed notes to the vector index.

    Create once (in lifespan), call sync() on demand or on a schedule.
    The engine is safe to call concurrently — each call is independent.
    """

    def __init__(
        self,
        scanner: VaultScanner,
        chunker: MarkdownChunker,
        embedding_provider: EmbeddingProvider,
        qdrant: VectorRepository,
        state_store: IndexStateStore,
        batch_size: int = 32,
    ) -> None:
        self._scanner = scanner
        self._chunker = chunker
        self._embedder = embedding_provider
        self._qdrant = qdrant
        self._state = state_store
        self._batch_size = batch_size
        self._last_run_at: datetime | None = None
        self._last_stats: SyncStats | None = None

    # ── Public API ─────────────────────────────────────────────────────────────

    async def sync(self) -> SyncStats:
        """Run an incremental sync. Returns accumulated stats."""
        stats = SyncStats()
        t_start = time.monotonic()

        await self._qdrant.ensure_collection()

        # Stage 1: Scan vault
        logger.info("Sync: scanning vault")
        scan_result = await self._scanner.scan()
        current: dict[str, str] = {n.relative_path: n.content_hash for n in scan_result.notes}
        note_by_path: dict[str, VaultNote] = {n.relative_path: n for n in scan_result.notes}

        # Stage 2: Load persisted state
        persisted: dict[str, str] = await self._state.load()

        # Stage 3: Diff
        current_paths = set(current)
        persisted_paths = set(persisted)
        common_paths = current_paths & persisted_paths

        new_paths = current_paths - persisted_paths
        deleted_paths = persisted_paths - current_paths
        modified_paths = {p for p in common_paths if current[p] != persisted[p]}
        unchanged_paths = common_paths - modified_paths

        stats.new_notes = len(new_paths)
        stats.modified_notes = len(modified_paths)
        stats.deleted_notes = len(deleted_paths)
        stats.unchanged_notes = len(unchanged_paths)

        logger.info(
            "Sync plan",
            extra={
                "new": stats.new_notes,
                "modified": stats.modified_notes,
                "deleted": stats.deleted_notes,
                "unchanged": stats.unchanged_notes,
            },
        )

        if not stats.has_changes:
            stats.duration_ms = _elapsed_ms(t_start)
            self._last_run_at = datetime.now(timezone.utc)
            self._last_stats = stats
            logger.info("Sync: no changes detected")
            return stats

        # Stage 4: Delete stale chunks (deleted notes + old version of modified notes)
        for path in deleted_paths:
            await self._delete_note_chunks(persisted[path], path, stats)

        for path in modified_paths:
            await self._delete_note_chunks(persisted[path], path, stats)

        # Stage 5: Embed + index new and modified notes
        notes_to_index = [note_by_path[p] for p in new_paths | modified_paths]
        if notes_to_index:
            await self._index_notes(notes_to_index, stats)

        # Stage 6: Persist updated state
        updated_state = {p: current[p] for p in current_paths}
        await self._state.save(updated_state)

        stats.duration_ms = _elapsed_ms(t_start)
        self._last_run_at = datetime.now(timezone.utc)
        self._last_stats = stats

        logger.info(
            "Sync complete",
            extra={
                "new_notes": stats.new_notes,
                "modified_notes": stats.modified_notes,
                "deleted_notes": stats.deleted_notes,
                "new_chunks": stats.new_chunks,
                "duration_ms": round(stats.duration_ms, 1),
                "errors": len(stats.errors),
            },
        )
        return stats

    @property
    def last_run_at(self) -> datetime | None:
        return self._last_run_at

    @property
    def last_stats(self) -> SyncStats | None:
        return self._last_stats

    @property
    def state_path(self) -> Path:
        return self._state.path

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _delete_note_chunks(
        self, note_id: str, path: str, stats: SyncStats
    ) -> None:
        try:
            await self._qdrant.delete_by_note_id(note_id)
            logger.debug("Deleted chunks", extra={"note_id": note_id, "path": path})
        except Exception as exc:
            msg = f"Failed to delete chunks for {path}: {exc}"
            logger.error(msg)
            stats.errors.append(msg)

    async def _index_notes(self, notes: list[VaultNote], stats: SyncStats) -> None:
        chunk_results = self._chunker.chunk_notes(notes)
        all_chunks: list[TextChunk] = []
        for cr in chunk_results:
            all_chunks.extend(cr.chunks)

        note_lookup: dict[str, VaultNote] = {n.content_hash: n for n in notes}
        now_iso = datetime.now(timezone.utc).isoformat()

        logger.info("Sync: embedding", extra={"notes": len(notes), "chunks": len(all_chunks)})

        for i in range(0, len(all_chunks), self._batch_size):
            batch = all_chunks[i : i + self._batch_size]
            await self._embed_and_index_batch(batch, note_lookup, now_iso, stats)

    async def _embed_and_index_batch(
        self,
        batch: list[TextChunk],
        note_lookup: dict[str, VaultNote],
        indexed_at: str,
        stats: SyncStats,
    ) -> None:
        texts = [chunk.text for chunk in batch]
        try:
            vectors = await self._embedder.embed_batch(texts)
        except Exception as exc:
            msg = f"Embedding batch failed: {exc}"
            logger.warning(msg)
            stats.errors.append(msg)
            return

        payloads = [_build_payload(chunk, note_lookup, indexed_at) for chunk in batch]
        try:
            await self._qdrant.upsert(payloads, vectors)
            stats.new_chunks += len(payloads)
        except Exception as exc:
            msg = f"Upsert batch failed: {exc}"
            logger.error(msg)
            stats.errors.append(msg)


# ── Module-level helpers ───────────────────────────────────────────────────────


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
        chunk_text=chunk.text,
        indexed_at=indexed_at,
        note_modified_at=note_modified_at,
    )


def _elapsed_ms(t_start: float) -> float:
    return round((time.monotonic() - t_start) * 1000, 1)
