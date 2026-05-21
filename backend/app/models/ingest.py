from typing import Literal

from pydantic import BaseModel


class IngestStatus(BaseModel):
    status: Literal["pending", "running", "completed", "failed"]
    total_notes: int = 0
    processed_notes: int = 0
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
