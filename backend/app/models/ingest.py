from typing import Literal

from pydantic import BaseModel


class SyncStatus(BaseModel):
    """Response model for POST /ingest/sync and GET /ingest/sync/status."""

    status: Literal["completed", "no_changes", "failed", "never_run"]
    new_notes: int = 0
    modified_notes: int = 0
    deleted_notes: int = 0
    unchanged_notes: int = 0
    new_chunks: int = 0
    duration_ms: float | None = None
    last_run_at: str | None = None
    scheduler_active: bool = False
    sync_interval_minutes: int = 0
    message: str | None = None


class IngestStatus(BaseModel):
    status: Literal["pending", "running", "completed", "failed"]
    total_notes: int = 0
    processed_notes: int = 0
    total_chunks: int = 0
    embedded_chunks: int = 0
    indexed_chunks: int = 0
    deleted_stale_chunks: int = 0
    duration_ms: float | None = None
    message: str | None = None


class NotePreview(BaseModel):
    relative_path: str
    title: str
    tags: list[str]
    wikilinks: list[str]
    heading_count: int
    file_size_bytes: int
    content_hash: str


class ScanResponse(BaseModel):
    total_files_scanned: int
    notes_found: int
    skipped_files: int
    scan_duration_ms: float
    vault_path: str
    notes: list[NotePreview]


# ── Chunking preview models ───────────────────────────────────────────────────


class ChunkPreview(BaseModel):
    id: str
    chunk_index: int
    heading_path: list[str]
    word_count: int
    text_preview: str       # first 200 characters of the decorated text


class NoteChunkPreview(BaseModel):
    relative_path: str
    title: str
    tags: list[str]
    content_hash: str
    total_chunks: int
    chunks: list[ChunkPreview]


class ChunkingPreviewResponse(BaseModel):
    vault_path: str
    notes_found: int
    total_chunks: int
    chunk_size: int
    chunk_overlap: int
    notes: list[NoteChunkPreview]
