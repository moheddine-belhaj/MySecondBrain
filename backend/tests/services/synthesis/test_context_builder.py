"""Unit tests for ContextBuilder, _format_citation_header, and _strip_breadcrumb."""

import pytest

from app.services.retrieval.models import RetrievedChunk
from app.services.synthesis.context_builder import (
    BuiltContext,
    ContextBuilder,
    _format_citation_header,
    _strip_breadcrumb,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_chunk(
    chunk_id: str = "c1",
    note_title: str = "My Note",
    chunk_text: str = "Some content here.",
    score: float = 0.90,
    heading_path: list[str] | None = None,
    note_path: str = "my-note.md",
    note_id: str = "nid1",
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        score=score,
        rank=1,
        chunk_text=chunk_text,
        note_title=note_title,
        note_path=note_path,
        note_id=note_id,
        tags=[],
        heading_path=heading_path or ["My Note"],
        chunk_index=0,
        total_chunks=1,
        word_count=3,
        indexed_at="2024-01-01T00:00:00+00:00",
        note_modified_at="2024-01-01T00:00:00+00:00",
    )


# ── Tests: ContextBuilder ─────────────────────────────────────────────────────


class TestContextBuilder:
    def test_empty_chunks_returns_empty_context(self):
        builder = ContextBuilder()
        result = builder.build([])
        assert result.context_str == ""
        assert result.included_chunks == []
        assert result.total_tokens == 0
        assert result.was_truncated is False

    def test_returns_built_context_type(self):
        builder = ContextBuilder()
        assert isinstance(builder.build([]), BuiltContext)

    def test_single_chunk_included(self):
        builder = ContextBuilder(max_context_tokens=1000)
        result = builder.build([_make_chunk()])
        assert len(result.included_chunks) == 1
        assert result.was_truncated is False

    def test_context_contains_citation_number(self):
        builder = ContextBuilder(max_context_tokens=1000)
        result = builder.build([_make_chunk()])
        assert "[1]" in result.context_str

    def test_context_contains_note_title(self):
        builder = ContextBuilder(max_context_tokens=1000)
        result = builder.build([_make_chunk(note_title="Research Notes")])
        assert "Research Notes" in result.context_str

    def test_context_contains_chunk_body(self):
        builder = ContextBuilder(max_context_tokens=1000)
        result = builder.build([_make_chunk(chunk_text="Unique body text.")])
        assert "Unique body text." in result.context_str

    def test_multiple_chunks_numbered_sequentially(self):
        builder = ContextBuilder(max_context_tokens=10_000)
        chunks = [_make_chunk(f"c{i}") for i in range(3)]
        result = builder.build(chunks)
        assert "[1]" in result.context_str
        assert "[2]" in result.context_str
        assert "[3]" in result.context_str

    def test_all_small_chunks_fit_in_large_budget(self):
        builder = ContextBuilder(max_context_tokens=10_000)
        chunks = [_make_chunk(f"c{i}") for i in range(5)]
        result = builder.build(chunks)
        assert len(result.included_chunks) == 5
        assert result.was_truncated is False

    def test_chunks_exceeding_budget_are_excluded(self):
        builder = ContextBuilder(max_context_tokens=50)
        chunks = [_make_chunk(f"c{i}", chunk_text="word " * 300) for i in range(5)]
        result = builder.build(chunks)
        assert len(result.included_chunks) < 5

    def test_sections_in_heading_path_appear_in_context(self):
        builder = ContextBuilder(max_context_tokens=1000)
        chunk = _make_chunk(heading_path=["My Note", "Key Concepts", "Embeddings"])
        result = builder.build([chunk])
        assert "Key Concepts" in result.context_str
        assert "Embeddings" in result.context_str

    def test_score_appears_in_context(self):
        builder = ContextBuilder(max_context_tokens=1000)
        result = builder.build([_make_chunk(score=0.87)])
        assert "0.87" in result.context_str

    def test_total_tokens_positive_for_nonempty_result(self):
        builder = ContextBuilder(max_context_tokens=1000)
        result = builder.build([_make_chunk()])
        assert result.total_tokens > 0

    def test_included_chunks_in_rank_order(self):
        builder = ContextBuilder(max_context_tokens=10_000)
        chunks = [_make_chunk(f"c{i}") for i in range(3)]
        result = builder.build(chunks)
        assert [c.chunk_id for c in result.included_chunks] == ["c0", "c1", "c2"]

    def test_breadcrumb_stripped_from_body(self):
        builder = ContextBuilder(max_context_tokens=1000)
        chunk = _make_chunk(chunk_text="[Note: My Note]\n\nActual body.")
        result = builder.build([chunk])
        assert "[Note: My Note]" not in result.context_str
        assert "Actual body." in result.context_str

    def test_was_truncated_false_when_all_fit(self):
        builder = ContextBuilder(max_context_tokens=10_000)
        result = builder.build([_make_chunk()])
        assert result.was_truncated is False


# ── Tests: _strip_breadcrumb ──────────────────────────────────────────────────


class TestStripBreadcrumb:
    def test_strips_simple_note_breadcrumb(self):
        text = "[Note: My Note]\n\nActual content here."
        assert _strip_breadcrumb(text) == "Actual content here."

    def test_strips_note_with_section(self):
        text = "[Note: My Note | Section: H2 > H3]\n\nContent."
        assert _strip_breadcrumb(text) == "Content."

    def test_no_breadcrumb_unchanged(self):
        text = "Plain content with no breadcrumb."
        assert _strip_breadcrumb(text) == text

    def test_non_note_bracket_unchanged(self):
        text = "[Something else]\n\nContent."
        assert _strip_breadcrumb(text) == text

    def test_breadcrumb_only_stripped_once(self):
        text = "[Note: A]\n\n[Note: B]\n\nContent."
        result = _strip_breadcrumb(text)
        assert "[Note: A]" not in result
        assert "[Note: B]" in result

    def test_empty_string_unchanged(self):
        assert _strip_breadcrumb("") == ""


# ── Tests: _format_citation_header ───────────────────────────────────────────


class TestFormatCitationHeader:
    def test_single_heading_no_sections(self):
        chunk = _make_chunk(note_title="My Note", heading_path=["My Note"], score=0.90)
        header = _format_citation_header(chunk, 1)
        assert header == "[1] My Note  (score: 0.90)"

    def test_citation_number_in_header(self):
        chunk = _make_chunk()
        header = _format_citation_header(chunk, 5)
        assert "[5]" in header

    def test_sections_joined_with_arrow(self):
        chunk = _make_chunk(heading_path=["My Note", "H2", "H3"])
        header = _format_citation_header(chunk, 1)
        assert "H2 > H3" in header

    def test_score_formatted_to_two_decimal_places(self):
        chunk = _make_chunk(score=0.857)
        header = _format_citation_header(chunk, 1)
        assert "0.86" in header

    def test_note_title_in_header(self):
        chunk = _make_chunk(note_title="Research Log")
        header = _format_citation_header(chunk, 1)
        assert "Research Log" in header
