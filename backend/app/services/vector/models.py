"""Vector payload schema — what Qdrant stores alongside each embedding vector.

Design notes
------------
Every field is a JSON-serialisable primitive or list of primitives. Qdrant
payload values must be scalars, lists of scalars, or nested dicts; we stay
with the simplest possible shape so payload filtering stays straightforward.

The payload is intentionally a superset of ChunkMetadata: it adds fields that
are only available at indexing time (indexed_at, note_modified_at) without
polluting the ingestion domain models.
"""

from dataclasses import dataclass


@dataclass
class VectorPayload:
    """All searchable / filterable metadata stored beside a Qdrant point.

    Stored as a plain dict via `to_dict()` — no Pydantic overhead at indexing
    time; Pydantic is only used at API boundaries.
    """

    chunk_id: str        # SHA-256 chunk ID (same as the Qdrant point ID)
    note_id: str         # VaultNote.content_hash — links chunk back to its note
    note_title: str
    note_path: str       # POSIX relative path inside the vault
    tags: list[str]      # inherited from the note; enables tag-based filtering
    heading_path: list[str]   # breadcrumb: [H1, H2, H3, ...]
    chunk_index: int     # 0-based position within the note
    total_chunks: int    # total chunks produced from this note
    word_count: int
    # ISO 8601 UTC strings — Qdrant does not have a native datetime type
    indexed_at: str      # when this point was written to Qdrant
    note_modified_at: str    # VaultNote.modified_at (file mtime, UTC)

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "note_id": self.note_id,
            "note_title": self.note_title,
            "note_path": self.note_path,
            "tags": self.tags,
            "heading_path": self.heading_path,
            "chunk_index": self.chunk_index,
            "total_chunks": self.total_chunks,
            "word_count": self.word_count,
            "indexed_at": self.indexed_at,
            "note_modified_at": self.note_modified_at,
        }
