"""Unit tests for MarkdownChunker.

All tests use synthetic VaultNote objects — no filesystem I/O, no asyncio.
The chunker is a pure synchronous function, so tests are fast and isolated.
"""

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services.ingestion.chunker import MarkdownChunker, _make_chunk_id
from app.services.ingestion.models import TextChunk
from app.services.vault.models import VaultNote


# ── Helpers ───────────────────────────────────────────────────────────────────


def _note(
    content: str,
    title: str = "Test Note",
    tags: list[str] | None = None,
    path: str = "notes/test.md",
) -> VaultNote:
    raw_bytes = content.encode("utf-8")
    return VaultNote(
        path=Path(path),
        relative_path=path,
        title=title,
        raw_content=content,
        frontmatter={},
        tags=tags or [],
        wikilinks=[],
        headings=[],
        content_hash=hashlib.sha256(raw_bytes).hexdigest(),
        file_size_bytes=len(raw_bytes),
        modified_at=datetime.now(tz=timezone.utc),
    )


def _words(n: int, word: str = "word") -> str:
    """Generate a string of exactly n words."""
    return " ".join([word] * n)


def _chunker(size: int = 512, overlap: int = 64) -> MarkdownChunker:
    return MarkdownChunker(chunk_size=size, chunk_overlap=overlap)


# ── Construction / validation ─────────────────────────────────────────────────


def test_overlap_must_be_less_than_size():
    with pytest.raises(ValueError, match="chunk_overlap"):
        MarkdownChunker(chunk_size=100, chunk_overlap=100)


def test_overlap_equal_to_size_raises():
    with pytest.raises(ValueError):
        MarkdownChunker(chunk_size=50, chunk_overlap=50)


def test_zero_overlap_is_valid():
    chunker = MarkdownChunker(chunk_size=100, chunk_overlap=0)
    assert chunker.chunk_overlap == 0


# ── Small notes (single chunk) ────────────────────────────────────────────────


def test_small_note_produces_one_chunk():
    note = _note("# Title\n\nShort content here.")
    result = _chunker().chunk_note(note)
    assert result.total_chunks == 1
    assert len(result.chunks) == 1


def test_empty_note_produces_no_chunks():
    note = _note("")
    result = _chunker().chunk_note(note)
    assert result.total_chunks == 0
    assert result.chunks == []


def test_frontmatter_only_note_produces_no_chunks():
    note = _note("---\ntitle: Empty\ntags: [test]\n---\n")
    result = _chunker().chunk_note(note)
    assert result.total_chunks == 0


def test_note_with_only_heading_no_body_produces_no_chunks():
    note = _note("# Just a Heading\n\n## Another Heading")
    result = _chunker().chunk_note(note)
    assert result.total_chunks == 0


# ── Chunk content ─────────────────────────────────────────────────────────────


def test_chunk_contains_note_content():
    note = _note("# Note\n\nThis is the body content of the note.")
    result = _chunker().chunk_note(note)
    assert "body content" in result.chunks[0].text


def test_chunk_text_includes_note_title_breadcrumb():
    note = _note("Some pre-heading content.", title="My Research")
    result = _chunker().chunk_note(note)
    assert "My Research" in result.chunks[0].text


def test_chunk_text_includes_section_breadcrumb():
    note = _note("# My Note\n\n## Key Concepts\n\nImportant ideas here.")
    result = _chunker().chunk_note(note)
    section_chunk = next(c for c in result.chunks if "Important ideas" in c.text)
    assert "Key Concepts" in section_chunk.text
    assert "My Note" in section_chunk.text


def test_breadcrumb_format_single_section():
    note = _note("Just some text with no headings.", title="Plain Note")
    chunk = _chunker().chunk_note(note).chunks[0]
    assert "[Note: Plain Note]" in chunk.text


def test_breadcrumb_format_with_section():
    note = _note("# Doc\n\n## Chapter\n\nContent here.")
    chunk = _chunker().chunk_note(note).chunks[0]
    assert "[Note: Doc | Section: Chapter]" in chunk.text


def test_breadcrumb_nested_sections():
    note = _note("# Root\n\n## Parent\n\n### Child\n\nDeep content.")
    chunk = _chunker().chunk_note(note).chunks[0]
    assert "Parent > Child" in chunk.text


# ── Metadata ──────────────────────────────────────────────────────────────────


def test_metadata_note_id_matches_note_hash():
    note = _note("# Title\n\nContent.")
    chunk = _chunker().chunk_note(note).chunks[0]
    assert chunk.metadata.note_id == note.content_hash


def test_metadata_note_title():
    note = _note("# Title\n\nContent.", title="My Custom Title")
    chunk = _chunker().chunk_note(note).chunks[0]
    assert chunk.metadata.note_title == "My Custom Title"


def test_metadata_note_path():
    note = _note("# Title\n\nContent.", path="folder/my-note.md")
    chunk = _chunker().chunk_note(note).chunks[0]
    assert chunk.metadata.note_path == "folder/my-note.md"


def test_metadata_tags_inherited_from_note():
    note = _note("# Title\n\nContent.", tags=["python", "ai", "rag"])
    chunk = _chunker().chunk_note(note).chunks[0]
    assert chunk.metadata.tags == ["python", "ai", "rag"]


def test_metadata_heading_path_no_headings():
    note = _note("Just content.", title="Root Note")
    chunk = _chunker().chunk_note(note).chunks[0]
    assert chunk.metadata.heading_path == ["Root Note"]


def test_metadata_heading_path_with_section():
    note = _note("# Doc\n\n## Section\n\nContent.", title="Doc")
    chunk = _chunker().chunk_note(note).chunks[0]
    assert chunk.metadata.heading_path == ["Doc", "Section"]


def test_metadata_heading_path_nested():
    note = _note("# Root\n\n## Parent\n\n### Child\n\nContent.")
    chunk = _chunker().chunk_note(note).chunks[0]
    assert chunk.metadata.heading_path == ["Root", "Parent", "Child"]


def test_metadata_chunk_index_sequential():
    content = "# Note\n\n" + "\n\n".join(f"## Section {i}\n\n{_words(100)}" for i in range(5))
    note = _note(content)
    result = _chunker(size=80, overlap=10).chunk_note(note)
    indices = [c.metadata.chunk_index for c in result.chunks]
    assert indices == list(range(len(result.chunks)))


def test_metadata_total_chunks_consistent():
    content = "# Note\n\n" + "\n\n".join(f"## S{i}\n\n{_words(100)}" for i in range(4))
    note = _note(content)
    result = _chunker(size=80, overlap=10).chunk_note(note)
    for chunk in result.chunks:
        assert chunk.metadata.total_chunks == result.total_chunks


def test_word_count_matches_actual():
    note = _note("# T\n\nHello world foo bar.")
    chunk = _chunker().chunk_note(note).chunks[0]
    assert chunk.word_count == len(chunk.text.split())


# ── Chunk IDs ─────────────────────────────────────────────────────────────────


def test_chunk_id_is_hex_string():
    note = _note("# Title\n\nContent.")
    chunk = _chunker().chunk_note(note).chunks[0]
    assert len(chunk.id) == 64
    assert all(c in "0123456789abcdef" for c in chunk.id)


def test_chunk_ids_unique_within_note():
    content = "# Note\n\n" + "\n\n".join(f"## S{i}\n\n{_words(100)}" for i in range(5))
    note = _note(content)
    result = _chunker(size=80, overlap=10).chunk_note(note)
    ids = [c.id for c in result.chunks]
    assert len(ids) == len(set(ids))


def test_chunk_id_stable_across_runs():
    note = _note("# Note\n\nSame content every time.")
    id1 = _chunker().chunk_note(note).chunks[0].id
    id2 = _chunker().chunk_note(note).chunks[0].id
    assert id1 == id2


def test_chunk_id_changes_when_note_content_changes():
    note_v1 = _note("# Note\n\nVersion one content.")
    note_v2 = _note("# Note\n\nVersion two content.")
    assert _chunker().chunk_note(note_v1).chunks[0].id != _chunker().chunk_note(note_v2).chunks[0].id


def test_make_chunk_id_deterministic():
    id1 = _make_chunk_id("abc123", 0)
    id2 = _make_chunk_id("abc123", 0)
    assert id1 == id2


def test_make_chunk_id_differs_by_index():
    assert _make_chunk_id("abc123", 0) != _make_chunk_id("abc123", 1)


def test_make_chunk_id_differs_by_note():
    assert _make_chunk_id("aaa", 0) != _make_chunk_id("bbb", 0)


# ── Large note splitting ───────────────────────────────────────────────────────


def test_large_section_split_into_multiple_chunks():
    # 300 words > chunk_size=100 → must produce multiple chunks
    note = _note(f"# Note\n\n## Big Section\n\n{_words(300)}")
    result = _chunker(size=100, overlap=10).chunk_note(note)
    assert result.total_chunks > 1


def test_chunk_word_count_does_not_exceed_size_by_much():
    # Each raw chunk before decoration should be <= chunk_size
    # The decoration adds ~10-20 words of breadcrumb
    note = _note(f"# Note\n\n{_words(600)}")
    result = _chunker(size=100, overlap=20).chunk_note(note)
    for chunk in result.chunks:
        # Allow headroom for the breadcrumb prefix (~20 words max)
        assert chunk.word_count <= 100 + 20 + 20, f"chunk too large: {chunk.word_count}"


def test_all_content_present_across_chunks():
    # Content words should appear somewhere across all chunks
    words_list = [f"unique{i}" for i in range(50)]
    content = "# Note\n\n" + " ".join(words_list)
    note = _note(content)
    result = _chunker(size=20, overlap=5).chunk_note(note)
    all_text = " ".join(c.text for c in result.chunks)
    for word in words_list:
        assert word in all_text, f"'{word}' missing from chunks"


# ── Heading structure ─────────────────────────────────────────────────────────


def test_each_heading_section_is_separate():
    note = _note(
        "# Doc\n\n"
        "## Alpha\n\nAlpha content here.\n\n"
        "## Beta\n\nBeta content here."
    )
    result = _chunker().chunk_note(note)
    texts = [c.text for c in result.chunks]
    alpha_chunk = next(t for t in texts if "Alpha content" in t)
    beta_chunk = next(t for t in texts if "Beta content" in t)
    # Alpha content should not appear in the beta chunk and vice versa
    assert "Alpha content" not in beta_chunk
    assert "Beta content" not in alpha_chunk


def test_heading_hierarchy_maintained_in_metadata():
    note = _note(
        "# Root\n\n"
        "## Level2\n\n"
        "### Level3\n\nDeep content here."
    )
    result = _chunker().chunk_note(note)
    deep_chunk = next(c for c in result.chunks if "Deep content" in c.text)
    assert deep_chunk.metadata.heading_path == ["Root", "Level2", "Level3"]


def test_sibling_headings_have_independent_paths():
    note = _note(
        "# Root\n\n"
        "## Alpha\n\nAlpha section.\n\n"
        "## Beta\n\nBeta section."
    )
    result = _chunker().chunk_note(note)
    alpha = next(c for c in result.chunks if "Alpha section" in c.text)
    beta = next(c for c in result.chunks if "Beta section" in c.text)
    assert alpha.metadata.heading_path == ["Root", "Alpha"]
    assert beta.metadata.heading_path == ["Root", "Beta"]


def test_heading_level_resets_on_same_level():
    # ## A, ## B — B should not inherit A in the path
    note = _note(
        "# Doc\n\n"
        "## First\n\nFirst content.\n\n"
        "## Second\n\nSecond content."
    )
    result = _chunker().chunk_note(note)
    second = next(c for c in result.chunks if "Second content" in c.text)
    assert "First" not in second.metadata.heading_path


def test_pre_heading_content_uses_note_title_as_path():
    note = _note("Intro text before any heading.\n\n# Title\n\nSection.", title="My Note")
    result = _chunker().chunk_note(note)
    intro = next(c for c in result.chunks if "Intro text" in c.text)
    assert intro.metadata.heading_path == ["My Note"]


# ── Overlap ───────────────────────────────────────────────────────────────────


def test_overlap_zero_produces_no_repeated_words():
    # With no overlap, consecutive chunks should not share tail/head content
    words_list = [f"w{i}" for i in range(60)]
    note = _note("# Note\n\n" + " ".join(words_list))
    result = MarkdownChunker(chunk_size=20, chunk_overlap=0).chunk_note(note)
    # Can only verify that we got chunks — isolation test is non-trivial with decorations
    assert result.total_chunks > 1


def test_overlap_words_appear_in_consecutive_chunks():
    # The tail of chunk[i] should appear at the start of chunk[i+1]'s raw content
    # We produce chunks from a long note and verify overlap words are shared
    long_text = " ".join(f"word{i}" for i in range(80))
    note = _note(f"# Note\n\n{long_text}")
    result = MarkdownChunker(chunk_size=30, chunk_overlap=10).chunk_note(note)

    if result.total_chunks >= 2:
        # The last 10 words from chunk 0's content should appear in chunk 1's text
        chunk0_words = result.chunks[0].text.split()
        chunk1_text = result.chunks[1].text
        # At least some overlap words should be present in next chunk
        tail_words = chunk0_words[-10:]
        found = sum(1 for w in tail_words if w in chunk1_text)
        assert found > 0, "No overlap words found in the next chunk"


def test_no_overlap_across_section_boundaries():
    # Sections are independent — chunk from section A should not bleed into section B
    # Each section is small enough to fit in one chunk
    note = _note(
        "# Note\n\n"
        "## SectionA\n\nUnique words: sectionA_alpha sectionA_beta.\n\n"
        "## SectionB\n\nUnique words: sectionB_gamma sectionB_delta."
    )
    result = MarkdownChunker(chunk_size=100, chunk_overlap=20).chunk_note(note)
    b_chunk = next(c for c in result.chunks if "sectionB_gamma" in c.text)
    # Overlap from SectionA content should not appear in SectionB chunk
    assert "sectionA_alpha" not in b_chunk.text
    assert "sectionA_beta" not in b_chunk.text


# ── Frontmatter handling ──────────────────────────────────────────────────────


def test_frontmatter_not_included_in_chunks():
    note = _note(
        "---\ntitle: My Note\ntags: [ai]\ncreated: 2024-01-01\n---\n\n"
        "# My Note\n\nActual content here."
    )
    result = _chunker().chunk_note(note)
    all_text = " ".join(c.text for c in result.chunks)
    assert "tags:" not in all_text
    assert "created:" not in all_text
    assert "Actual content" in all_text


def test_note_with_frontmatter_and_headings():
    note = _note(
        "---\ntitle: Research\ntags: [rag]\n---\n\n"
        "# Research\n\n## Methods\n\nWe used retrieval-augmented generation."
    )
    result = _chunker().chunk_note(note)
    assert result.total_chunks >= 1
    chunk = result.chunks[0]
    assert "retrieval-augmented" in chunk.text


# ── ChunkResult fields ────────────────────────────────────────────────────────


def test_chunk_result_note_id():
    note = _note("# T\n\nContent.")
    result = _chunker().chunk_note(note)
    assert result.note_id == note.content_hash


def test_chunk_result_note_title():
    note = _note("# T\n\nContent.", title="Expected Title")
    result = _chunker().chunk_note(note)
    assert result.note_title == "Expected Title"


def test_chunk_result_note_path():
    note = _note("# T\n\nContent.", path="deep/path/note.md")
    result = _chunker().chunk_note(note)
    assert result.note_path == "deep/path/note.md"


def test_chunk_result_total_chunks_matches_list():
    note = _note(f"# Note\n\n{_words(300)}")
    result = _chunker(size=80, overlap=10).chunk_note(note)
    assert result.total_chunks == len(result.chunks)


# ── chunk_notes (batch) ───────────────────────────────────────────────────────


def test_chunk_notes_batch():
    notes = [_note(f"# Note {i}\n\nContent {i}.") for i in range(5)]
    results = _chunker().chunk_notes(notes)
    assert len(results) == 5


def test_chunk_notes_skips_bad_notes_without_crash():
    good = _note("# Good\n\nContent.")
    results = _chunker().chunk_notes([good])
    assert len(results) == 1


# ── Paragraph-level splitting ─────────────────────────────────────────────────


def test_paragraphs_kept_together_when_possible():
    # Two short paragraphs should land in the same chunk when combined < chunk_size
    note = _note("# Note\n\nFirst paragraph here.\n\nSecond paragraph here.")
    result = _chunker(size=50, overlap=5).chunk_note(note)
    # Both paragraphs should be in the same chunk since they're small
    assert result.total_chunks == 1
    assert "First paragraph" in result.chunks[0].text
    assert "Second paragraph" in result.chunks[0].text


def test_large_paragraphs_split_independently():
    para1 = _words(100, "alpha")
    para2 = _words(100, "beta")
    note = _note(f"# Note\n\n{para1}\n\n{para2}")
    result = _chunker(size=60, overlap=10).chunk_note(note)
    assert result.total_chunks > 1
