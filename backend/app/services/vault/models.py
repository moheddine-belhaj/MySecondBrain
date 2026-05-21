from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Heading:
    level: int  # 1–6
    text: str


@dataclass
class VaultNote:
    """Internal representation of a single parsed Obsidian note.

    Intentionally a plain dataclass (not Pydantic) — it lives entirely
    inside the service layer and never crosses an API boundary directly.
    The ingestion pipeline will transform it into Pydantic models / Qdrant
    payloads as needed.
    """

    path: Path
    relative_path: str          # POSIX, relative to vault root — portable & JSON-safe
    title: str
    raw_content: str
    frontmatter: dict[str, Any]
    tags: list[str]             # deduplicated, lowercased; frontmatter + inline #tags
    wikilinks: list[str]        # link targets only (alias stripped), order-preserving
    headings: list[Heading]
    content_hash: str           # SHA-256 hex of raw bytes — stable ID for incremental indexing
    file_size_bytes: int
    modified_at: datetime       # UTC-aware mtime
    created_at: datetime | None = None  # from frontmatter "created" / "date" if present


@dataclass
class ScanResult:
    notes: list[VaultNote]
    total_files_scanned: int    # all files, including skipped
    skipped_files: int          # unsupported extensions + parse failures
    scan_duration_ms: float
    vault_path: str
