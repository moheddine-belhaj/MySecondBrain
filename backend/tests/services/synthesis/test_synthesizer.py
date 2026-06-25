"""Unit tests for ResponseSynthesizer and _chunk_to_node."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.retrieval.models import RetrievedChunk
from app.services.synthesis.synthesizer import ResponseSynthesizer, _chunk_to_node


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_chunk(
    chunk_id: str = "c1",
    score: float = 0.9,
    chunk_text: str = "Some note text.",
    note_title: str = "My Note",
    note_path: str = "my-note.md",
    note_id: str = "note1",
    tags: list[str] | None = None,
    heading_path: list[str] | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        score=score,
        rank=1,
        chunk_text=chunk_text,
        note_title=note_title,
        note_path=note_path,
        note_id=note_id,
        tags=tags or [],
        heading_path=heading_path or ["H1"],
        chunk_index=0,
        total_chunks=3,
        word_count=10,
        indexed_at="2024-01-01T00:00:00+00:00",
        note_modified_at="2024-01-01T00:00:00+00:00",
    )


def _make_synthesizer(response_text: str = "Test answer.") -> tuple[ResponseSynthesizer, MagicMock]:
    """Create a ResponseSynthesizer with the internal LlamaIndex synth mocked."""
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.response = response_text

    with patch(
        "app.services.synthesis.synthesizer.get_response_synthesizer"
    ) as mock_factory:
        mock_synth = MagicMock()
        mock_synth.asynthesize = AsyncMock(return_value=mock_response)
        mock_factory.return_value = mock_synth

        synthesizer = ResponseSynthesizer(llm=mock_llm, mode="compact")
        return synthesizer, mock_synth


# ── Tests: _chunk_to_node ─────────────────────────────────────────────────────

class TestChunkToNode:
    def test_node_text_is_chunk_text(self):
        chunk = _make_chunk(chunk_text="RAG means retrieval-augmented generation.")
        node_with_score = _chunk_to_node(chunk)
        assert node_with_score.node.text == "RAG means retrieval-augmented generation."

    def test_score_is_preserved(self):
        chunk = _make_chunk(score=0.87)
        node_with_score = _chunk_to_node(chunk)
        assert node_with_score.score == 0.87

    def test_node_id_is_chunk_id(self):
        chunk = _make_chunk(chunk_id="abc-123")
        node_with_score = _chunk_to_node(chunk)
        assert node_with_score.node.id_ == "abc-123"

    def test_metadata_contains_note_title(self):
        chunk = _make_chunk(note_title="Deep Learning Notes")
        node_with_score = _chunk_to_node(chunk)
        assert node_with_score.node.metadata["note_title"] == "Deep Learning Notes"

    def test_metadata_contains_note_path(self):
        chunk = _make_chunk(note_path="ai/deep-learning.md")
        node_with_score = _chunk_to_node(chunk)
        assert node_with_score.node.metadata["note_path"] == "ai/deep-learning.md"

    def test_metadata_contains_tags(self):
        chunk = _make_chunk(tags=["ai", "ml"])
        node_with_score = _chunk_to_node(chunk)
        assert node_with_score.node.metadata["tags"] == ["ai", "ml"]

    def test_metadata_contains_heading_path(self):
        chunk = _make_chunk(heading_path=["Introduction", "Background"])
        node_with_score = _chunk_to_node(chunk)
        assert node_with_score.node.metadata["heading_path"] == ["Introduction", "Background"]

    def test_metadata_contains_chunk_id(self):
        chunk = _make_chunk(chunk_id="xyz")
        node_with_score = _chunk_to_node(chunk)
        assert node_with_score.node.metadata["chunk_id"] == "xyz"


# ── Tests: ResponseSynthesizer ────────────────────────────────────────────────

class TestResponseSynthesizer:
    async def test_empty_chunks_returns_fallback(self):
        synthesizer, _ = _make_synthesizer()
        result = await synthesizer.synthesize("What is RAG?", chunks=[])
        assert "couldn't find" in result.answer.lower()
        assert result.source_chunks == []
        assert result.latency_ms == 0.0

    async def test_asynthesize_called_with_query(self):
        synthesizer, mock_synth = _make_synthesizer("Answer here.")
        chunks = [_make_chunk()]
        await synthesizer.synthesize("What is attention?", chunks=chunks)
        call_args = mock_synth.asynthesize.call_args
        assert call_args.args[0] == "What is attention?"

    async def test_asynthesize_called_with_nodes(self):
        synthesizer, mock_synth = _make_synthesizer("Answer here.")
        chunks = [_make_chunk("c1"), _make_chunk("c2")]
        await synthesizer.synthesize("query", chunks=chunks)
        call_kwargs = mock_synth.asynthesize.call_args.kwargs
        assert len(call_kwargs["nodes"]) == 2

    async def test_answer_from_response(self):
        synthesizer, _ = _make_synthesizer("This is the synthesized answer.")
        result = await synthesizer.synthesize("query", chunks=[_make_chunk()])
        assert result.answer == "This is the synthesized answer."

    async def test_source_chunks_preserved(self):
        synthesizer, _ = _make_synthesizer("answer")
        chunks = [_make_chunk("c1"), _make_chunk("c2")]
        result = await synthesizer.synthesize("query", chunks=chunks)
        assert len(result.source_chunks) == 2
        assert result.source_chunks[0].chunk_id == "c1"
        assert result.source_chunks[1].chunk_id == "c2"

    async def test_latency_ms_is_non_negative(self):
        synthesizer, _ = _make_synthesizer("answer")
        result = await synthesizer.synthesize("query", chunks=[_make_chunk()])
        assert result.latency_ms >= 0.0

    async def test_none_response_returns_fallback(self):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.response = None

        with patch("app.services.synthesis.synthesizer.get_response_synthesizer") as mock_factory:
            mock_synth = MagicMock()
            mock_synth.asynthesize = AsyncMock(return_value=mock_response)
            mock_factory.return_value = mock_synth
            synthesizer = ResponseSynthesizer(llm=mock_llm, mode="compact")

        result = await synthesizer.synthesize("query", chunks=[_make_chunk()])
        assert len(result.answer) > 0

    async def test_factory_called_with_correct_mode(self):
        mock_llm = MagicMock()
        with patch("app.services.synthesis.synthesizer.get_response_synthesizer") as mock_factory:
            mock_synth = MagicMock()
            mock_synth.asynthesize = AsyncMock(return_value=MagicMock(response="ok"))
            mock_factory.return_value = mock_synth

            ResponseSynthesizer(llm=mock_llm, mode="refine")
            call_kwargs = mock_factory.call_args.kwargs
            assert call_kwargs["response_mode"].value == "refine"
