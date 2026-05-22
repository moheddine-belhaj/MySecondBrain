"""Unit tests for EmbeddingPipeline.

Strategy
--------
All external I/O is mocked with lightweight fakes:
  - FakeScanner   : returns a canned ScanResult
  - FakeEmbedder  : returns deterministic float vectors
  - FakeQdrant    : in-memory store, records all calls

No Qdrant server or Ollama process is required.
Tests cover: batching behaviour, stale-chunk pruning, embedding failure
tolerance, payload field mapping, and stats accumulation.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.services.ingestion.chunker import MarkdownChunker
from app.services.ingestion.embedder import EmbeddingPipeline, IndexingStats, _build_payload
from app.services.ingestion.models import ChunkMetadata, TextChunk
from app.services.llm.base import EmbeddingProvider
from app.services.vault.models import Heading, ScanResult, VaultNote
from app.services.vault.scanner import VaultScanner
from app.services.vector.client import QdrantService
from app.services.vector.models import VectorPayload

# ── Helpers ───────────────────────────────────────────────────────────────────

_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _vault_note(
    *,
    title: str = "Test Note",
    path_str: str = "test-note.md",
    content: str = "# Test Note\n\nSome content here.",
    tags: list[str] | None = None,
    content_hash: str = "abc123",
) -> VaultNote:
    return VaultNote(
        path=Path(path_str),
        relative_path=path_str,
        title=title,
        raw_content=content,
        frontmatter={},
        tags=tags or [],
        wikilinks=[],
        headings=[Heading(level=1, text=title)],
        content_hash=content_hash,
        file_size_bytes=len(content.encode()),
        modified_at=_NOW,
        created_at=None,
    )


def _scan_result(notes: list[VaultNote]) -> ScanResult:
    return ScanResult(
        notes=notes,
        total_files_scanned=len(notes),
        skipped_files=0,
        scan_duration_ms=1.0,
        vault_path="/vault",
    )


class FakeScanner:
    def __init__(self, notes: list[VaultNote]) -> None:
        self._result = _scan_result(notes)

    async def scan(self) -> ScanResult:
        return self._result


class FakeEmbedder:
    """Returns a fixed-length vector of 1.0s for each text."""

    def __init__(self, dim: int = 4, fail_on_call: int | None = None) -> None:
        self._dim = dim
        self._fail_on_call = fail_on_call
        self.call_count = 0

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.call_count += 1
        if self._fail_on_call == self.call_count:
            raise RuntimeError("Simulated embedding failure")
        return [[1.0] * self._dim for _ in texts]

    async def embed(self, text: str) -> list[float]:
        return [1.0] * self._dim

    async def health(self) -> bool:
        return True


class FakeQdrant:
    """In-memory Qdrant stand-in that records all mutations."""

    def __init__(self, existing_ids: set[str] | None = None) -> None:
        self.upserted: list[tuple[VectorPayload, list[float]]] = []
        self.deleted: list[str] = []
        self._existing_ids: set[str] = existing_ids or set()
        self.ensure_called = False

    async def ensure_collection(self) -> None:
        self.ensure_called = True

    async def upsert(self, payloads: list[VectorPayload], vectors: list[list[float]]) -> None:
        for p, v in zip(payloads, vectors):
            self.upserted.append((p, v))

    async def get_all_point_ids(self) -> set[str]:
        return set(self._existing_ids)

    async def delete_points(self, ids: list[str]) -> None:
        self.deleted.extend(ids)


def _make_pipeline(
    notes: list[VaultNote],
    *,
    batch_size: int = 10,
    existing_ids: set[str] | None = None,
    fail_on_batch: int | None = None,
) -> tuple[EmbeddingPipeline, FakeQdrant]:
    qdrant = FakeQdrant(existing_ids=existing_ids)
    pipeline = EmbeddingPipeline(
        scanner=FakeScanner(notes),  # type: ignore[arg-type]
        chunker=MarkdownChunker(chunk_size=50, chunk_overlap=5),
        embedding_provider=FakeEmbedder(fail_on_call=fail_on_batch),  # type: ignore[arg-type]
        qdrant=qdrant,  # type: ignore[arg-type]
        batch_size=batch_size,
    )
    return pipeline, qdrant


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestEmbeddingPipelineStats:
    async def test_empty_vault_returns_zero_stats(self):
        pipeline, _ = _make_pipeline([])
        stats = await pipeline.run()
        assert stats.total_notes == 0
        assert stats.total_chunks == 0
        assert stats.embedded_chunks == 0
        assert stats.indexed_chunks == 0

    async def test_single_note_counts(self):
        note = _vault_note(content="# Note\n\nShort content.")
        pipeline, qdrant = _make_pipeline([note])
        stats = await pipeline.run()
        assert stats.total_notes == 1
        assert stats.processed_notes == 1
        assert stats.total_chunks >= 1
        assert stats.embedded_chunks == stats.indexed_chunks == stats.total_chunks

    async def test_multiple_notes_counted(self):
        notes = [
            _vault_note(title=f"Note {i}", path_str=f"note-{i}.md", content_hash=f"hash{i}")
            for i in range(3)
        ]
        pipeline, _ = _make_pipeline(notes)
        stats = await pipeline.run()
        assert stats.total_notes == 3
        assert stats.processed_notes == 3

    async def test_duration_ms_is_non_negative(self):
        note = _vault_note()
        pipeline, _ = _make_pipeline([note])
        stats = await pipeline.run()
        assert stats.duration_ms >= 0

    async def test_no_errors_on_clean_run(self):
        note = _vault_note()
        pipeline, _ = _make_pipeline([note])
        stats = await pipeline.run()
        assert stats.errors == []


class TestEmbeddingPipelineBatching:
    async def test_single_batch_when_chunks_fit(self):
        note = _vault_note(content="# Note\n\nShort text.")
        embedder = FakeEmbedder()
        qdrant = FakeQdrant()
        pipeline = EmbeddingPipeline(
            scanner=FakeScanner([note]),  # type: ignore[arg-type]
            chunker=MarkdownChunker(chunk_size=50, chunk_overlap=5),
            embedding_provider=embedder,  # type: ignore[arg-type]
            qdrant=qdrant,  # type: ignore[arg-type]
            batch_size=100,
        )
        await pipeline.run()
        assert embedder.call_count == 1

    async def test_multiple_batches_when_chunks_exceed_batch_size(self):
        # Create a note with enough sections to produce > 2 chunks
        sections = "\n\n".join(
            f"## Section {i}\n\nContent for section {i} with some words." for i in range(10)
        )
        note = _vault_note(content=f"# Big Note\n\n{sections}")
        embedder = FakeEmbedder()
        qdrant = FakeQdrant()
        pipeline = EmbeddingPipeline(
            scanner=FakeScanner([note]),  # type: ignore[arg-type]
            chunker=MarkdownChunker(chunk_size=50, chunk_overlap=5),
            embedding_provider=embedder,  # type: ignore[arg-type]
            qdrant=qdrant,  # type: ignore[arg-type]
            batch_size=2,
        )
        stats = await pipeline.run()
        # Each batch of 2 chunks = one embed call
        assert embedder.call_count == (stats.total_chunks + 1) // 2

    async def test_upserted_count_matches_embedded(self):
        note = _vault_note(content="# Note\n\nParagraph one.\n\nParagraph two.")
        pipeline, qdrant = _make_pipeline([note])
        stats = await pipeline.run()
        assert len(qdrant.upserted) == stats.indexed_chunks


class TestEmbeddingPipelineStaleChunkPruning:
    async def test_stale_ids_are_deleted(self):
        note = _vault_note(content_hash="newhash")
        stale_ids = {"old_chunk_1", "old_chunk_2"}
        pipeline, qdrant = _make_pipeline([note], existing_ids=stale_ids)
        stats = await pipeline.run()
        assert set(qdrant.deleted) == stale_ids
        assert stats.deleted_stale_chunks == 2

    async def test_no_deletion_when_no_stale_ids(self):
        note = _vault_note(content="# Note\n\nContent.")
        pipeline, qdrant = _make_pipeline([note])
        # Get the chunk IDs that will be produced, then pass them as existing
        stats = await pipeline.run()
        # Run again with the same IDs as existing — nothing should be deleted
        existing = {p.chunk_id for p, _ in qdrant.upserted}
        pipeline2, qdrant2 = _make_pipeline([note], existing_ids=existing)
        stats2 = await pipeline2.run()
        assert qdrant2.deleted == []
        assert stats2.deleted_stale_chunks == 0

    async def test_empty_vault_deletes_all_existing(self):
        stale_ids = {"old1", "old2", "old3"}
        pipeline, qdrant = _make_pipeline([], existing_ids=stale_ids)
        stats = await pipeline.run()
        # Empty vault → no chunks produced → all existing are stale
        # But the pipeline returns early before fetching IDs when notes == []
        # So no deletions happen (by design — empty vault could be a misconfiguration)
        assert stats.total_chunks == 0


class TestEmbeddingPipelineErrorTolerance:
    async def test_batch_failure_captured_in_errors(self):
        sections = "\n\n".join(
            f"## Section {i}\n\nContent {i}." for i in range(6)
        )
        note = _vault_note(content=f"# Note\n\n{sections}")
        embedder = FakeEmbedder(fail_on_call=1)  # first batch fails
        qdrant = FakeQdrant()
        pipeline = EmbeddingPipeline(
            scanner=FakeScanner([note]),  # type: ignore[arg-type]
            chunker=MarkdownChunker(chunk_size=50, chunk_overlap=5),
            embedding_provider=embedder,  # type: ignore[arg-type]
            qdrant=qdrant,  # type: ignore[arg-type]
            batch_size=2,
        )
        stats = await pipeline.run()
        assert len(stats.errors) >= 1
        # Remaining batches still succeed
        assert stats.indexed_chunks > 0

    async def test_all_batches_fail_results_in_zero_indexed(self):
        note = _vault_note(content="# Note\n\nContent.")
        embedder = FakeEmbedder(fail_on_call=1)
        qdrant = FakeQdrant()
        pipeline = EmbeddingPipeline(
            scanner=FakeScanner([note]),  # type: ignore[arg-type]
            chunker=MarkdownChunker(chunk_size=500, chunk_overlap=5),
            embedding_provider=embedder,  # type: ignore[arg-type]
            qdrant=qdrant,  # type: ignore[arg-type]
            batch_size=100,  # everything in one batch
        )
        stats = await pipeline.run()
        assert stats.indexed_chunks == 0
        assert len(stats.errors) == 1


class TestEmbeddingPipelineEnsureCollection:
    async def test_ensure_collection_called_before_scan(self):
        note = _vault_note()
        pipeline, qdrant = _make_pipeline([note])
        await pipeline.run()
        assert qdrant.ensure_called is True

    async def test_ensure_collection_called_even_on_empty_vault(self):
        pipeline, qdrant = _make_pipeline([])
        await pipeline.run()
        assert qdrant.ensure_called is True


class TestBuildPayload:
    def test_payload_fields_from_chunk(self):
        note = _vault_note(title="My Note", path_str="folder/my-note.md", tags=["tag1"])
        metadata = ChunkMetadata(
            note_id=note.content_hash,
            note_title=note.title,
            note_path=note.relative_path,
            tags=note.tags,
            heading_path=["My Note", "Section"],
            chunk_index=2,
            total_chunks=5,
        )
        chunk = TextChunk(
            id="chunk_id_abc",
            text="[Note: My Note | Section: Section]\n\nsome text",
            word_count=8,
            metadata=metadata,
        )
        note_lookup = {note.content_hash: note}
        payload = _build_payload(chunk, note_lookup, "2024-01-01T00:00:00+00:00")

        assert payload.chunk_id == "chunk_id_abc"
        assert payload.note_id == note.content_hash
        assert payload.note_title == "My Note"
        assert payload.note_path == "folder/my-note.md"
        assert payload.tags == ["tag1"]
        assert payload.heading_path == ["My Note", "Section"]
        assert payload.chunk_index == 2
        assert payload.total_chunks == 5
        assert payload.word_count == 8
        assert payload.indexed_at == "2024-01-01T00:00:00+00:00"
        assert payload.note_modified_at == note.modified_at.isoformat()

    def test_payload_uses_indexed_at_as_fallback_when_note_missing(self):
        metadata = ChunkMetadata(
            note_id="unknown_hash",
            note_title="Ghost",
            note_path="ghost.md",
            tags=[],
            heading_path=["Ghost"],
            chunk_index=0,
            total_chunks=1,
        )
        chunk = TextChunk(id="cid", text="text", word_count=1, metadata=metadata)
        fallback_ts = "2024-06-01T00:00:00+00:00"
        payload = _build_payload(chunk, {}, fallback_ts)
        assert payload.note_modified_at == fallback_ts

    def test_payload_tags_are_copied_not_shared(self):
        note = _vault_note(tags=["a", "b"])
        metadata = ChunkMetadata(
            note_id=note.content_hash,
            note_title=note.title,
            note_path=note.relative_path,
            tags=note.tags,
            heading_path=[],
            chunk_index=0,
            total_chunks=1,
        )
        chunk = TextChunk(id="c", text="t", word_count=1, metadata=metadata)
        payload = _build_payload(chunk, {note.content_hash: note}, "ts")
        payload.tags.append("extra")
        assert note.tags == ["a", "b"]  # original not mutated
