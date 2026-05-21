"""Markdown-aware chunking pipeline for Obsidian notes.

Chunking strategy overview
--------------------------
Naive fixed-size chunking (e.g. "every 512 characters") produces poor RAG
results because it blindly splits across sentence, paragraph, and heading
boundaries, destroying the semantic units that make retrieval accurate.

This pipeline uses a three-stage approach:

Stage 1 — Section splitting (heading-aware)
    The document body is split at Markdown ATX heading markers.
    Each (heading → next-heading) slice becomes an independent section.
    A heading stack is maintained so every section knows its full ancestor
    chain: [note_title, "Chapter 1", "Section 1.2", "Subsection 1.2.3"].
    Chunks never cross section boundaries, so retrieved text always belongs
    to exactly one coherent topic.

Stage 2 — Recursive text splitting (separator-hierarchy)
    Within each section, the text is split using an ordered separator list:

        paragraph break  →  \n\n
        line break       →  \n
        sentence end     →  ".  " / "!  " / "?  "
        word boundary    →  " "   (last resort)

    The algorithm tries the broadest separator first. If all resulting
    pieces fit within chunk_size words, we stop. If any piece is still
    too large, we recurse with the next narrower separator. This preserves
    paragraphs > sentences > words — in that priority order.

Stage 3 — Overlap injection
    After raw chunks are produced for a section, the last `chunk_overlap`
    words from chunk[i] are prepended to chunk[i+1].  Overlap is scoped
    to a single section: we do not carry context across heading boundaries
    because mixing content from different topics degrades embedding quality.

    Overlap purpose: if a key fact sits at the boundary between two chunks,
    at least one chunk will contain it in full — improving recall for
    queries that touch boundary content.

Context decoration
    Every chunk's text is prefixed with a heading breadcrumb:

        [Note: My Research Note | Section: Key Concepts > Embeddings]

        ...chunk content here...

    The breadcrumb is baked into the text before embedding, so the model
    encodes topical context even for chunks that contain only a few sentences.
    Without this, a short chunk like "See the formula above." is uninterpretable
    in isolation at retrieval time.

Chunk ID
    Each chunk gets a deterministic SHA-256 ID:  SHA256(note_id + ":" + index)
    When note content changes → note_id (its SHA-256 hash) changes → all
    chunk IDs change → Qdrant can detect and replace stale vectors cheaply.

Limitations (known, out of scope for this task)
    - Code blocks may be split mid-block (no fenced-code awareness).
    - Very long single-line paragraphs fall back to word-level splitting,
      which loses whitespace structure.
    - Word count is used as a proxy for token count (1 word ≈ 1.3 tokens
      for English); actual tokenizer can be swapped in without API changes.
"""

import hashlib
import logging
import re
from dataclasses import dataclass

from app.services.ingestion.models import ChunkMetadata, ChunkResult, TextChunk
from app.services.vault.models import VaultNote
from app.services.vault.parser import MarkdownParser

logger = logging.getLogger("app.services.ingestion")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)(?:\s+#+)?\s*$", re.MULTILINE)

# Ordered from broadest to narrowest — recursive split tries these in sequence
_SEPARATORS = ["\n\n", "\n", ". ", "! ", "? ", " "]


@dataclass
class _Section:
    """Internal: a contiguous block of text under one heading."""

    heading_path: list[str]  # [note_title, ancestor_h2, ..., current_heading]
    text: str                # raw section text, no sub-headings included


class MarkdownChunker:
    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64) -> None:
        if chunk_overlap >= chunk_size:
            raise ValueError(
                f"chunk_overlap ({chunk_overlap}) must be less than chunk_size ({chunk_size})"
            )
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    # ── Public API ─────────────────────────────────────────────────────────────

    def chunk_note(self, note: VaultNote) -> ChunkResult:
        """Produce all chunks for a single VaultNote."""
        _, body = MarkdownParser.extract_frontmatter(note.raw_content)
        sections = self._split_into_sections(body, note.title)

        raw_texts: list[str] = []
        heading_paths: list[list[str]] = []

        for section in sections:
            if not section.text.strip():
                continue
            for chunk_text in self._chunk_section(section.text):
                if chunk_text.strip():
                    raw_texts.append(chunk_text)
                    heading_paths.append(section.heading_path)

        total = len(raw_texts)
        chunks: list[TextChunk] = []

        for idx, (raw_text, heading_path) in enumerate(zip(raw_texts, heading_paths)):
            text = self._add_context(raw_text, note.title, heading_path)
            chunks.append(
                TextChunk(
                    id=_make_chunk_id(note.content_hash, idx),
                    text=text,
                    word_count=len(text.split()),
                    metadata=ChunkMetadata(
                        note_id=note.content_hash,
                        note_title=note.title,
                        note_path=note.relative_path,
                        tags=list(note.tags),
                        heading_path=list(heading_path),
                        chunk_index=idx,
                        total_chunks=total,
                    ),
                )
            )

        logger.debug(
            "Note chunked",
            extra={
                "note": note.relative_path,
                "chunks": total,
                "chunk_size": self.chunk_size,
                "chunk_overlap": self.chunk_overlap,
            },
        )

        return ChunkResult(
            note_id=note.content_hash,
            note_title=note.title,
            note_path=note.relative_path,
            chunks=chunks,
            total_chunks=total,
        )

    def chunk_notes(self, notes: list[VaultNote]) -> list[ChunkResult]:
        """Chunk a list of notes. Failures on individual notes are logged and skipped."""
        results: list[ChunkResult] = []
        for note in notes:
            try:
                results.append(self.chunk_note(note))
            except Exception as exc:
                logger.warning(
                    "Failed to chunk note",
                    extra={"path": note.relative_path, "error": str(exc)},
                )
        return results

    # ── Stage 1: Section splitting ─────────────────────────────────────────────

    def _split_into_sections(self, body: str, note_title: str) -> list[_Section]:
        """Split the document body into sections at heading boundaries.

        A heading stack is maintained so each section knows its full ancestor
        chain, enabling per-chunk heading breadcrumbs.
        """
        heading_matches = list(_HEADING_RE.finditer(body))
        sections: list[_Section] = []
        heading_stack: list[tuple[int, str]] = []  # (level, text)

        # Content before the first heading
        pre_text = (
            body[: heading_matches[0].start()].strip() if heading_matches else body.strip()
        )
        if pre_text:
            sections.append(_Section(heading_path=[note_title], text=pre_text))

        for i, match in enumerate(heading_matches):
            level = len(match.group(1))
            heading_text = match.group(2).strip()

            # Pop headings of the same or deeper level — they are "closed" by this heading
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, heading_text))

            start = match.end()
            end = (
                heading_matches[i + 1].start()
                if i + 1 < len(heading_matches)
                else len(body)
            )
            section_text = body[start:end].strip()

            if not section_text:
                continue  # heading immediately followed by a sub-heading

            # Use the document heading stack directly as the path.
            # Only fall back to note_title as root when there is no H1 in the
            # ancestor chain (e.g. the note starts with ## or ###).
            path_texts = [t for _, t in heading_stack]
            if not heading_stack or heading_stack[0][0] > 1:
                path_texts = [note_title] + path_texts
            sections.append(_Section(heading_path=path_texts, text=section_text))

        return sections

    # ── Stage 2: Recursive text splitting ─────────────────────────────────────

    def _chunk_section(self, text: str) -> list[str]:
        """Split section text into sized chunks, then add overlap."""
        raw = self._split_recursive(text, _SEPARATORS)
        return self._apply_overlap(raw)

    def _split_recursive(self, text: str, separators: list[str]) -> list[str]:
        """Try to split using the first separator. Recurse with narrower ones
        for pieces that are still too large. Falls back to word-level split
        when no separator remains.
        """
        if len(text.split()) <= self.chunk_size:
            return [text.strip()] if text.strip() else []

        if not separators:
            # Absolute last resort — breaks whitespace structure but always correct
            words = text.split()
            return [
                " ".join(words[i : i + self.chunk_size])
                for i in range(0, len(words), self.chunk_size)
            ]

        sep, *rest = separators
        pieces = [p for p in text.split(sep) if p.strip()]

        if len(pieces) <= 1:
            # Separator not present in this text — try the next one
            return self._split_recursive(text, rest)

        chunks: list[str] = []
        current_pieces: list[str] = []
        current_words = 0

        for piece in pieces:
            piece_words = len(piece.split())

            if current_words + piece_words <= self.chunk_size:
                current_pieces.append(piece)
                current_words += piece_words
            else:
                # Flush what we've accumulated
                if current_pieces:
                    chunks.append(sep.join(current_pieces))

                if piece_words > self.chunk_size:
                    # Piece itself too large — recurse with narrower separator
                    sub = self._split_recursive(piece, rest)
                    if sub:
                        # All sub-chunks except the last go directly to output;
                        # the last one seeds the next accumulation cycle
                        chunks.extend(sub[:-1])
                        current_pieces = [sub[-1]]
                        current_words = len(sub[-1].split())
                    else:
                        current_pieces = []
                        current_words = 0
                else:
                    current_pieces = [piece]
                    current_words = piece_words

        if current_pieces:
            chunks.append(sep.join(current_pieces))

        return chunks

    # ── Stage 3: Overlap injection ─────────────────────────────────────────────

    def _apply_overlap(self, chunks: list[str]) -> list[str]:
        """Prepend the last `chunk_overlap` words of chunk[i] to chunk[i+1].

        Overlap is based on the raw chunk text (before decoration), so the
        boundary region appears verbatim in both adjacent chunks without
        compounding prefix noise.
        """
        if self.chunk_overlap <= 0 or len(chunks) <= 1:
            return chunks

        result: list[str] = [chunks[0]]
        for i in range(1, len(chunks)):
            tail_words = chunks[i - 1].split()[-self.chunk_overlap :]
            tail = " ".join(tail_words)
            result.append(f"{tail}\n\n{chunks[i]}" if tail else chunks[i])

        return result

    # ── Context decoration ─────────────────────────────────────────────────────

    def _add_context(self, text: str, note_title: str, heading_path: list[str]) -> str:
        """Prepend a heading breadcrumb so the embedding captures full context.

        Pre-heading / no sections:
            [Note: My Note]

            chunk text here...

        Section content:
            [Note: Research Log | Section: Experiments > Results]

            chunk text here...

        `note_title` comes from VaultNote.title (frontmatter > H1 > stem).
        `heading_path` is the document heading stack and may differ from
        note_title when they were derived independently.
        """
        # heading_path[0] is the document H1 (or note_title for pre-heading content).
        # Display it as the "[Note: ...]" identifier; sub-headings go into "[Section: ...]".
        display_title = heading_path[0] if heading_path else note_title
        sections = heading_path[1:]
        if sections:
            header = f"[Note: {display_title} | Section: {' > '.join(sections)}]\n\n"
        else:
            header = f"[Note: {display_title}]\n\n"
        return header + text


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_chunk_id(note_id: str, chunk_index: int) -> str:
    """Deterministic, content-addressable chunk ID.

    Changes when either the note content (note_id) or the chunk position
    (chunk_index) changes. Qdrant can use this to detect stale vectors.
    """
    return hashlib.sha256(f"{note_id}:{chunk_index}".encode()).hexdigest()
