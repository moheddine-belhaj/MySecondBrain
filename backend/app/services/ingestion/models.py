from dataclasses import dataclass


@dataclass
class ChunkMetadata:
    """All context a chunk carries besides its text.

    Stored alongside the embedding vector in Qdrant (Task 7).
    Every field is a scalar or a plain list — no nested objects — so it
    serialises directly to a Qdrant payload dict without any transformation.
    """

    note_id: str            # VaultNote.content_hash — links chunk back to its note
    note_title: str
    note_path: str          # POSIX relative path inside the vault
    tags: list[str]         # inherited from the note (for tag-based filtering)
    heading_path: list[str] # breadcrumb: [note_title, h2_text, h3_text, ...]
    chunk_index: int        # 0-based position within the note
    total_chunks: int       # total chunks produced from this note


@dataclass
class TextChunk:
    """A single indexable unit ready to be embedded.

    `text` is the content that gets passed to the embedding model.
    It includes a heading breadcrumb prefix so every chunk is self-contained
    when retrieved in isolation.

    `id` is deterministic: SHA-256(note_id + ":" + chunk_index).
    Changing note content changes note_id, which changes all chunk IDs,
    making stale-chunk detection trivial in Task 7.
    """

    id: str
    text: str           # decorated text (breadcrumb + raw content)
    word_count: int
    metadata: ChunkMetadata


@dataclass
class ChunkResult:
    note_id: str
    note_title: str
    note_path: str
    chunks: list[TextChunk]
    total_chunks: int
