"""Unit tests for IncrementalSyncEngine.

Strategy
--------
All external I/O is replaced with lightweight fakes:
  - FakeScanner     : returns a canned list of VaultNotes
  - FakeEmbedder    : returns deterministic float vectors, can simulate failure
  - FakeQdrant      : in-memory store, records every delete_by_note_id / upsert call
  - FakeStateStore  : in-memory {path: hash} dict, no filesystem required

Tests cover: all-new vault, no-changes, modified note, deleted note, mixed
scenario, embed failure tolerance, state persistence after sync.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services.indexing.state_store import IndexStateStore
from app.services.indexing.sync_engine import IncrementalSyncEngine, SyncStats
from app.services.ingestion.chunker import MarkdownChunker
from app.services.vault.models import Heading, ScanResult, VaultNote
from app.services.vector.models import VectorPayload

_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


# ── Fakes ─────────────────────────────────────────────────────────────────────


def _note(
    path: str = "note.md",
    content_hash: str = "hash-aaa",
    content: str = "# Note\n\nContent.",
) -> VaultNote:
    return VaultNote(
        path=Path(path),
        relative_path=path,
        title=path.replace(".md", ""),
        raw_content=content,
        frontmatter={},
        tags=[],
        wikilinks=[],
        headings=[Heading(level=1, text="Note")],
        content_hash=content_hash,
        file_size_bytes=len(content.encode()),
        modified_at=_NOW,
        created_at=None,
    )


class FakeScanner:
    def __init__(self, notes: list[VaultNote]) -> None:
        self._notes = notes

    async def scan(self) -> ScanResult:
        return ScanResult(
            notes=self._notes,
            total_files_scanned=len(self._notes),
            skipped_files=0,
            scan_duration_ms=1.0,
            vault_path="/vault",
        )


class FakeEmbedder:
    def __init__(self, dim: int = 4, fail_on_call: int | None = None) -> None:
        self._dim = dim
        self._fail_on = fail_on_call
        self.call_count = 0

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.call_count += 1
        if self._fail_on == self.call_count:
            raise RuntimeError("Simulated embed failure")
        return [[1.0] * self._dim for _ in texts]

    async def embed(self, text: str) -> list[float]:
        return [1.0] * self._dim

    async def health(self) -> bool:
        return True


class FakeQdrant:
    def __init__(self) -> None:
        self.upserted: list[VectorPayload] = []
        self.deleted_note_ids: list[str] = []
        self.ensure_called = False

    async def ensure_collection(self) -> None:
        self.ensure_called = True

    async def upsert(self, payloads: list[VectorPayload], vectors: list[list[float]]) -> None:
        self.upserted.extend(payloads)

    async def delete_by_note_id(self, note_id: str) -> None:
        self.deleted_note_ids.append(note_id)

    async def get_all_point_ids(self) -> set[str]:
        return set()

    async def delete_points(self, ids: list[str]) -> None:
        pass

    async def update_payload(self, chunk_id: str, updates: dict) -> None:
        pass

    async def search(self, *args, **kwargs):
        return []

    async def count(self) -> int:
        return 0

    async def get_collection_info(self):
        return None

    async def delete_collection(self) -> None:
        pass

    async def health(self) -> bool:
        return True


class FakeStateStore:
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._data: dict[str, str] = initial or {}
        self.saved: list[dict[str, str]] = []

    async def load(self) -> dict[str, str]:
        return dict(self._data)

    async def save(self, state: dict[str, str]) -> None:
        self._data = dict(state)
        self.saved.append(dict(state))

    @property
    def path(self) -> Path:
        return Path("/fake/state.json")


# ── Fixture ───────────────────────────────────────────────────────────────────


def _engine(
    notes: list[VaultNote],
    persisted: dict[str, str] | None = None,
    fail_on_embed: int | None = None,
) -> tuple[IncrementalSyncEngine, FakeQdrant, FakeStateStore]:
    qdrant = FakeQdrant()
    state_store = FakeStateStore(initial=persisted)
    embedder = FakeEmbedder(fail_on_call=fail_on_embed)
    chunker = MarkdownChunker(chunk_size=128, chunk_overlap=16)
    scanner = FakeScanner(notes)
    engine = IncrementalSyncEngine(
        scanner=scanner,
        chunker=chunker,
        embedding_provider=embedder,
        qdrant=qdrant,
        state_store=state_store,
        batch_size=32,
    )
    return engine, qdrant, state_store


# ── Tests: IndexStateStore integration ────────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_collection_called_on_sync() -> None:
    engine, qdrant, _ = _engine(notes=[_note()])
    await engine.sync()
    assert qdrant.ensure_called


# ── Tests: all-new vault ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_all_new_notes_indexed() -> None:
    """Empty persisted state → every note is treated as new."""
    notes = [_note("a.md", "h-a"), _note("b.md", "h-b")]
    engine, qdrant, state_store = _engine(notes, persisted={})

    stats = await engine.sync()

    assert stats.new_notes == 2
    assert stats.modified_notes == 0
    assert stats.deleted_notes == 0
    assert stats.unchanged_notes == 0
    assert stats.new_chunks > 0
    assert not stats.errors
    assert stats.has_changes


@pytest.mark.asyncio
async def test_all_new_state_saved() -> None:
    notes = [_note("a.md", "h-a"), _note("b.md", "h-b")]
    engine, _, state_store = _engine(notes, persisted={})

    await engine.sync()

    assert len(state_store.saved) == 1
    saved = state_store.saved[0]
    assert saved == {"a.md": "h-a", "b.md": "h-b"}


# ── Tests: no changes ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_changes_returns_no_changes() -> None:
    """Same hashes in vault and state → nothing to do."""
    notes = [_note("a.md", "h-a"), _note("b.md", "h-b")]
    engine, qdrant, state_store = _engine(notes, persisted={"a.md": "h-a", "b.md": "h-b"})

    stats = await engine.sync()

    assert not stats.has_changes
    assert stats.unchanged_notes == 2
    assert qdrant.upserted == []
    assert qdrant.deleted_note_ids == []


@pytest.mark.asyncio
async def test_no_changes_state_not_saved() -> None:
    """State file is NOT written when there are no changes (early return)."""
    notes = [_note("a.md", "h-a")]
    engine, _, state_store = _engine(notes, persisted={"a.md": "h-a"})

    await engine.sync()

    assert state_store.saved == []


# ── Tests: modified note ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_modified_note_deletes_old_and_embeds_new() -> None:
    """When a note's hash changes, old chunks are deleted and new ones embedded."""
    old_hash = "h-old"
    new_hash = "h-new"
    note = _note("a.md", new_hash)
    engine, qdrant, _ = _engine([note], persisted={"a.md": old_hash})

    stats = await engine.sync()

    assert stats.modified_notes == 1
    assert stats.new_notes == 0
    assert stats.deleted_notes == 0
    assert old_hash in qdrant.deleted_note_ids
    assert stats.new_chunks > 0


@pytest.mark.asyncio
async def test_modified_note_delete_happens_before_embed() -> None:
    """Verify delete-before-embed ordering via call sequence recording."""
    events: list[str] = []

    class OrderTrackingQdrant(FakeQdrant):
        async def delete_by_note_id(self, note_id: str) -> None:
            events.append(f"delete:{note_id}")

        async def upsert(self, payloads, vectors) -> None:
            events.append("upsert")

    note = _note("a.md", "h-new")
    state_store = FakeStateStore(initial={"a.md": "h-old"})
    engine = IncrementalSyncEngine(
        scanner=FakeScanner([note]),
        chunker=MarkdownChunker(chunk_size=128, chunk_overlap=16),
        embedding_provider=FakeEmbedder(),
        qdrant=OrderTrackingQdrant(),
        state_store=state_store,
        batch_size=32,
    )

    await engine.sync()

    assert events.index("delete:h-old") < events.index("upsert")


# ── Tests: deleted note ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deleted_note_removed_from_qdrant() -> None:
    """A note in persisted state but absent from vault is deleted from Qdrant."""
    engine, qdrant, _ = _engine(notes=[], persisted={"gone.md": "h-gone"})

    stats = await engine.sync()

    assert stats.deleted_notes == 1
    assert "h-gone" in qdrant.deleted_note_ids
    assert stats.new_notes == 0
    assert stats.unchanged_notes == 0


@pytest.mark.asyncio
async def test_deleted_note_removed_from_state() -> None:
    notes = [_note("keep.md", "h-keep")]
    engine, _, state_store = _engine(notes, persisted={"keep.md": "h-keep", "gone.md": "h-gone"})

    await engine.sync()

    assert "gone.md" not in state_store.saved[-1]
    assert "keep.md" in state_store.saved[-1]


# ── Tests: mixed scenario ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mixed_scenario() -> None:
    """new + modified + deleted + unchanged all in one sync."""
    notes = [
        _note("new.md", "h-new"),
        _note("modified.md", "h-modified-v2"),
        _note("unchanged.md", "h-unchanged"),
    ]
    persisted = {
        "modified.md": "h-modified-v1",
        "unchanged.md": "h-unchanged",
        "deleted.md": "h-deleted",
    }
    engine, qdrant, state_store = _engine(notes, persisted=persisted)

    stats = await engine.sync()

    assert stats.new_notes == 1
    assert stats.modified_notes == 1
    assert stats.deleted_notes == 1
    assert stats.unchanged_notes == 1
    assert stats.new_chunks > 0
    assert not stats.errors
    assert "h-modified-v1" in qdrant.deleted_note_ids
    assert "h-deleted" in qdrant.deleted_note_ids

    saved = state_store.saved[-1]
    assert "deleted.md" not in saved
    assert saved["new.md"] == "h-new"
    assert saved["modified.md"] == "h-modified-v2"
    assert saved["unchanged.md"] == "h-unchanged"


# ── Tests: error handling ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_embed_failure_recorded_in_errors() -> None:
    """If embedding fails, the error is captured in stats — no exception raised."""
    notes = [_note("a.md", "h-a")]
    engine, _, _ = _engine(notes, persisted={}, fail_on_embed=1)

    stats = await engine.sync()

    assert len(stats.errors) == 1
    assert "Embedding batch failed" in stats.errors[0] or "Simulated embed failure" in stats.errors[0]


@pytest.mark.asyncio
async def test_embed_failure_does_not_crash_engine() -> None:
    notes = [_note("a.md", "h-a")]
    engine, _, _ = _engine(notes, persisted={}, fail_on_embed=1)

    stats = await engine.sync()

    assert isinstance(stats, SyncStats)


# ── Tests: last_run_at / last_stats properties ───────────────────────────────


@pytest.mark.asyncio
async def test_last_run_at_none_before_sync() -> None:
    engine, _, _ = _engine(notes=[])
    assert engine.last_run_at is None


@pytest.mark.asyncio
async def test_last_run_at_set_after_sync() -> None:
    notes = [_note()]
    engine, _, _ = _engine(notes, persisted={})
    await engine.sync()
    assert engine.last_run_at is not None


@pytest.mark.asyncio
async def test_last_stats_none_before_sync() -> None:
    engine, _, _ = _engine(notes=[])
    assert engine.last_stats is None


@pytest.mark.asyncio
async def test_last_stats_reflects_most_recent_run() -> None:
    notes = [_note("a.md", "h-a")]
    engine, _, _ = _engine(notes, persisted={})
    stats = await engine.sync()
    assert engine.last_stats is stats


# ── Tests: SyncStats.has_changes ─────────────────────────────────────────────


def test_has_changes_true_when_new() -> None:
    s = SyncStats(new_notes=1)
    assert s.has_changes


def test_has_changes_true_when_modified() -> None:
    s = SyncStats(modified_notes=1)
    assert s.has_changes


def test_has_changes_true_when_deleted() -> None:
    s = SyncStats(deleted_notes=1)
    assert s.has_changes


def test_has_changes_false_when_only_unchanged() -> None:
    s = SyncStats(unchanged_notes=5)
    assert not s.has_changes
