"""Unit tests for RetrievalEngine."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.retrieval.engine import RetrievalEngine, _has_active_filters, _to_retrieved_chunk
from app.services.retrieval.models import RetrievalQuery
from app.services.vector.models import SearchFilter, SearchResult


# ── Helpers ───────────────────────────────────────────────────────────────────

VECTOR = [0.1, 0.2, 0.3, 0.4]


def _search_result(
    chunk_id: str = "c1",
    score: float = 0.9,
    note_id: str = "note1",
    heading_path: list[str] | None = None,
    note_title: str = "My Note",
    note_path: str = "my-note.md",
    tags: list[str] | None = None,
    chunk_index: int = 0,
    total_chunks: int = 3,
    word_count: int = 100,
) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        score=score,
        chunk_text=f"text of {chunk_id}",
        payload={
            "note_id": note_id,
            "note_title": note_title,
            "note_path": note_path,
            "tags": tags or [],
            "heading_path": heading_path or [],
            "chunk_index": chunk_index,
            "total_chunks": total_chunks,
            "word_count": word_count,
            "indexed_at": "2024-01-01T00:00:00+00:00",
            "note_modified_at": "2024-01-01T00:00:00+00:00",
        },
    )


def _make_engine(search_returns: list[SearchResult] | None = None) -> tuple[RetrievalEngine, MagicMock, MagicMock]:
    embedder = MagicMock()
    embedder.embed = AsyncMock(return_value=VECTOR)

    qdrant = MagicMock()
    qdrant.search = AsyncMock(return_value=search_returns or [])

    engine = RetrievalEngine(
        embedding_provider=embedder,
        qdrant=qdrant,
        default_top_k=10,
        default_score_threshold=0.0,
        default_max_chunks_per_note=2,
        default_over_fetch_factor=3,
    )
    return engine, embedder, qdrant


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestRetrievalEngineBasic:
    async def test_returns_retrieval_result(self):
        engine, _, _ = _make_engine([_search_result()])
        result = await engine.retrieve(RetrievalQuery(text="what is AI?"))
        assert result.query == "what is AI?"
        assert len(result.chunks) == 1

    async def test_empty_qdrant_returns_empty_result(self):
        engine, _, _ = _make_engine([])
        result = await engine.retrieve(RetrievalQuery(text="query"))
        assert result.chunks == []
        assert result.total_candidates == 0
        assert result.deduplicated_count == 0

    async def test_query_embedded_before_search(self):
        engine, embedder, qdrant = _make_engine([])
        await engine.retrieve(RetrievalQuery(text="hello"))
        embedder.embed.assert_awaited_once_with("hello")
        qdrant.search.assert_awaited_once()

    async def test_embed_vector_passed_to_qdrant(self):
        engine, _, qdrant = _make_engine([])
        await engine.retrieve(RetrievalQuery(text="q"))
        call_kwargs = qdrant.search.call_args.kwargs
        assert call_kwargs["query_vector"] == VECTOR

    async def test_latency_ms_is_non_negative(self):
        engine, _, _ = _make_engine([])
        result = await engine.retrieve(RetrievalQuery(text="q"))
        assert result.latency_ms >= 0.0


class TestRetrievalEngineOverFetch:
    async def test_over_fetch_multiplies_top_k(self):
        engine, _, qdrant = _make_engine([])
        await engine.retrieve(RetrievalQuery(text="q", top_k=5, over_fetch_factor=4))
        call_kwargs = qdrant.search.call_args.kwargs
        assert call_kwargs["limit"] == 20  # 5 × 4

    async def test_result_trimmed_to_top_k(self):
        results = [_search_result(chunk_id=str(i), score=1.0 - i * 0.05, note_id=f"note{i}", heading_path=[f"S{i}"]) for i in range(10)]
        engine, _, _ = _make_engine(results)
        result = await engine.retrieve(RetrievalQuery(text="q", top_k=3, over_fetch_factor=3))
        assert len(result.chunks) <= 3


class TestRetrievalEngineFilters:
    async def test_filters_passed_to_qdrant(self):
        engine, _, qdrant = _make_engine([])
        f = SearchFilter(tags=["ai"])
        await engine.retrieve(RetrievalQuery(text="q", filters=f))
        call_kwargs = qdrant.search.call_args.kwargs
        assert call_kwargs["filters"] == f

    async def test_score_threshold_passed_to_qdrant(self):
        engine, _, qdrant = _make_engine([])
        await engine.retrieve(RetrievalQuery(text="q", score_threshold=0.7))
        call_kwargs = qdrant.search.call_args.kwargs
        assert call_kwargs["score_threshold"] == 0.7

    async def test_filters_applied_true_when_tags_set(self):
        engine, _, _ = _make_engine([])
        result = await engine.retrieve(RetrievalQuery(text="q", filters=SearchFilter(tags=["python"])))
        assert result.filters_applied is True

    async def test_filters_applied_false_when_no_filters(self):
        engine, _, _ = _make_engine([])
        result = await engine.retrieve(RetrievalQuery(text="q"))
        assert result.filters_applied is False

    async def test_filters_applied_false_when_filter_object_all_none(self):
        engine, _, _ = _make_engine([])
        result = await engine.retrieve(RetrievalQuery(text="q", filters=SearchFilter()))
        assert result.filters_applied is False


class TestRetrievalEngineDedup:
    async def test_dedup_removes_duplicate_headings(self):
        results = [
            _search_result("a", 0.9, note_id="note1", heading_path=["H1"]),
            _search_result("b", 0.8, note_id="note1", heading_path=["H1"]),
        ]
        engine, _, _ = _make_engine(results)
        result = await engine.retrieve(RetrievalQuery(text="q", deduplicate=True, top_k=10))
        assert len(result.chunks) == 1
        assert result.deduplicated_count == 1

    async def test_dedup_false_keeps_all(self):
        results = [
            _search_result("a", 0.9, note_id="note1", heading_path=["H1"]),
            _search_result("b", 0.8, note_id="note1", heading_path=["H1"]),
        ]
        engine, _, _ = _make_engine(results)
        result = await engine.retrieve(RetrievalQuery(text="q", deduplicate=False, top_k=10))
        assert len(result.chunks) == 2
        assert result.deduplicated_count == 0

    async def test_total_candidates_reflects_pre_dedup_count(self):
        results = [
            _search_result("a", 0.9, note_id="note1", heading_path=["H1"]),
            _search_result("b", 0.8, note_id="note1", heading_path=["H1"]),
            _search_result("c", 0.7, note_id="note2", heading_path=["H2"]),
        ]
        engine, _, _ = _make_engine(results)
        result = await engine.retrieve(RetrievalQuery(text="q", deduplicate=True, top_k=10))
        assert result.total_candidates == 3


class TestRetrievalEngineRanking:
    async def test_chunks_have_1_based_rank(self):
        results = [
            _search_result("a", 0.9, note_id="note1", heading_path=["S1"]),
            _search_result("b", 0.8, note_id="note2", heading_path=["S1"]),
            _search_result("c", 0.7, note_id="note3", heading_path=["S1"]),
        ]
        engine, _, _ = _make_engine(results)
        result = await engine.retrieve(RetrievalQuery(text="q", top_k=5))
        ranks = [c.rank for c in result.chunks]
        assert ranks == list(range(1, len(ranks) + 1))

    async def test_highest_score_is_rank_1(self):
        results = [
            _search_result("a", 0.9, note_id="n1", heading_path=["S1"]),
            _search_result("b", 0.7, note_id="n2", heading_path=["S1"]),
        ]
        engine, _, _ = _make_engine(results)
        result = await engine.retrieve(RetrievalQuery(text="q", top_k=5))
        assert result.chunks[0].rank == 1
        assert result.chunks[0].score >= result.chunks[1].score


class TestToRetrievedChunk:
    def test_maps_all_fields(self):
        r = _search_result(
            chunk_id="cid",
            score=0.88,
            note_id="nid",
            note_title="Title",
            note_path="path.md",
            tags=["a", "b"],
            heading_path=["H1", "H2"],
            chunk_index=2,
            total_chunks=5,
            word_count=200,
        )
        chunk = _to_retrieved_chunk(r, rank=3)
        assert chunk.chunk_id == "cid"
        assert chunk.score == 0.88
        assert chunk.rank == 3
        assert chunk.chunk_text == "text of cid"
        assert chunk.note_title == "Title"
        assert chunk.note_path == "path.md"
        assert chunk.note_id == "nid"
        assert chunk.tags == ["a", "b"]
        assert chunk.heading_path == ["H1", "H2"]
        assert chunk.chunk_index == 2
        assert chunk.total_chunks == 5
        assert chunk.word_count == 200


class TestHasActiveFilters:
    def test_none_filter_is_false(self):
        q = RetrievalQuery(text="q", filters=None)
        assert _has_active_filters(q) is False

    def test_empty_filter_object_is_false(self):
        q = RetrievalQuery(text="q", filters=SearchFilter())
        assert _has_active_filters(q) is False

    def test_tags_makes_true(self):
        q = RetrievalQuery(text="q", filters=SearchFilter(tags=["x"]))
        assert _has_active_filters(q) is True

    def test_note_id_makes_true(self):
        q = RetrievalQuery(text="q", filters=SearchFilter(note_id="abc"))
        assert _has_active_filters(q) is True

    def test_note_path_makes_true(self):
        q = RetrievalQuery(text="q", filters=SearchFilter(note_path="a/b.md"))
        assert _has_active_filters(q) is True

    def test_note_title_makes_true(self):
        q = RetrievalQuery(text="q", filters=SearchFilter(note_title="My Note"))
        assert _has_active_filters(q) is True
