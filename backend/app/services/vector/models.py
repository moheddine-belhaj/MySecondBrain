"""Vector service domain models.

VectorPayload    — the dict stored alongside each Qdrant point.
SearchFilter     — caller-facing filter spec (Python, not Qdrant-specific).
SearchResult     — a single hit returned from a vector search.
CollectionInfo   — summary of a Qdrant collection's current state.

Design rule: everything here is pure Python (dataclasses, no Qdrant imports).
FilterBuilder in filters.py is the only place that imports qdrant_client models.
"""

from dataclasses import dataclass, field


@dataclass
class VectorPayload:
    """All metadata stored beside a Qdrant point at index time.

    `chunk_text` stores the full decorated text (breadcrumb + raw content)
    so search results are self-contained — no vault lookup needed at retrieval.

    `to_dict()` produces the exact dict written to Qdrant payload.
    All values are JSON-serialisable scalars or lists of scalars.
    """

    chunk_id: str         # SHA-256 chunk ID (== Qdrant point ID)
    note_id: str          # VaultNote.content_hash
    note_title: str
    note_path: str        # POSIX relative path inside the vault
    tags: list[str]       # inherited from note; indexed for tag-based filtering
    heading_path: list[str]   # breadcrumb: [H1, H2, H3, ...]
    chunk_index: int      # 0-based position within the note
    total_chunks: int
    word_count: int
    chunk_text: str       # decorated text (breadcrumb + content) as embedded
    # ISO 8601 UTC strings — Qdrant has no native datetime type
    indexed_at: str
    note_modified_at: str

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
            "chunk_text": self.chunk_text,
            "indexed_at": self.indexed_at,
            "note_modified_at": self.note_modified_at,
        }


@dataclass
class SearchFilter:
    """Caller-facing filter spec — provider-neutral Python types.

    FilterBuilder.build() converts this to a Qdrant Filter object.
    All fields are optional; unset fields are ignored.

    tags       : match chunks whose note has ANY of these tags.
    note_id    : exact hash match — retrieve all chunks of one note.
    note_path  : exact path match — e.g. "folder/my-note.md".
    note_title : exact title match — e.g. "My Research Note".
    """

    tags: list[str] | None = None
    note_id: str | None = None
    note_path: str | None = None
    note_title: str | None = None


@dataclass
class SearchResult:
    """A single hit from a vector search.

    `score`      : cosine similarity in [0, 1] — higher is more similar.
    `chunk_text` : the decorated text stored at index time; ready to pass
                   to the LLM as context without a vault lookup.
    `payload`    : full Qdrant payload dict for any field the caller needs.
    """

    chunk_id: str
    score: float
    chunk_text: str
    payload: dict = field(default_factory=dict)


@dataclass
class CollectionInfo:
    """Summary of a Qdrant collection's configuration and current state."""

    name: str
    vector_count: int    # number of indexed points
    vector_size: int     # embedding dimension
    distance: str        # "Cosine", "Euclid", or "Dot"
    status: str          # "green" | "yellow" | "red" | "grey"
