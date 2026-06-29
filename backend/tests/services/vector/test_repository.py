"""Tests for FilterBuilder and QdrantService.

Strategy
--------
FilterBuilder  — pure Python logic, no mocking needed.
QdrantService  — all AsyncQdrantClient calls are mocked with AsyncMock/MagicMock.
                 Tests verify the correct Qdrant API is called with the correct
                 parameters. No Qdrant server required.
"""

from unittest.mock import AsyncMock, MagicMock, call

import pytest
from qdrant_client.http import models as qmodels

from app.services.vector.client import QdrantService, _INTEGER_INDEXES, _KEYWORD_INDEXES, _to_point_id
from app.services.vector.filters import FilterBuilder
from app.services.vector.models import CollectionInfo, SearchFilter, SearchResult, VectorPayload


# ── Test chunk IDs (must be ≥32 hex chars so _to_point_id can form a UUID) ────

_CHUNK_ID_1 = "a" * 32
_CHUNK_ID_2 = "b" * 32
_CHUNK_ID_3 = "c" * 32


# ── Shared helpers ────────────────────────────────────────────────────────────


def _make_client() -> MagicMock:
    client = MagicMock()
    client.collection_exists = AsyncMock(return_value=False)
    client.create_collection = AsyncMock()
    client.create_payload_index = AsyncMock()
    client.upsert = AsyncMock()
    client.query_points = AsyncMock(return_value=MagicMock(points=[]))
    client.delete = AsyncMock()
    client.set_payload = AsyncMock()
    client.count = AsyncMock(return_value=MagicMock(count=0))
    client.get_collection = AsyncMock()
    client.delete_collection = AsyncMock()
    client.get_collections = AsyncMock()
    client.scroll = AsyncMock(return_value=([], None))
    return client


def _make_service(client=None) -> tuple[QdrantService, MagicMock]:
    if client is None:
        client = _make_client()
    return QdrantService(client=client, collection_name="test_col", vector_size=4), client


def _payload(**overrides) -> VectorPayload:
    defaults = dict(
        chunk_id=_CHUNK_ID_1,
        note_id="nid1",
        note_title="Note",
        note_path="note.md",
        tags=["ai"],
        heading_path=["Note"],
        chunk_index=0,
        total_chunks=1,
        word_count=10,
        chunk_text="[Note: Note]\n\ncontent",
        indexed_at="2024-01-01T00:00:00+00:00",
        note_modified_at="2024-01-01T00:00:00+00:00",
    )
    defaults.update(overrides)
    return VectorPayload(**defaults)


def _scored_point(chunk_id: str, score: float, payload: dict | None = None) -> MagicMock:
    point = MagicMock()
    point.id = chunk_id
    point.score = score
    point.payload = payload or {"chunk_text": "text", "note_title": "N"}
    return point


# ── FilterBuilder tests ───────────────────────────────────────────────────────


class TestFilterBuilder:
    def test_none_input_returns_none(self):
        assert FilterBuilder.build(None) is None

    def test_empty_filter_returns_none(self):
        assert FilterBuilder.build(SearchFilter()) is None

    def test_tags_filter_uses_match_any(self):
        f = FilterBuilder.build(SearchFilter(tags=["ai", "ml"]))
        assert f is not None
        assert len(f.must) == 1
        cond = f.must[0]
        assert cond.key == "tags"
        assert isinstance(cond.match, qmodels.MatchAny)
        assert cond.match.any == ["ai", "ml"]

    def test_single_tag_works(self):
        f = FilterBuilder.build(SearchFilter(tags=["python"]))
        assert f is not None
        assert f.must[0].match.any == ["python"]

    def test_note_id_filter_uses_match_value(self):
        f = FilterBuilder.build(SearchFilter(note_id="hash123"))
        assert f is not None
        assert len(f.must) == 1
        cond = f.must[0]
        assert cond.key == "note_id"
        assert isinstance(cond.match, qmodels.MatchValue)
        assert cond.match.value == "hash123"

    def test_note_path_filter(self):
        f = FilterBuilder.build(SearchFilter(note_path="folder/my-note.md"))
        assert f is not None
        cond = f.must[0]
        assert cond.key == "note_path"
        assert cond.match.value == "folder/my-note.md"

    def test_note_title_filter(self):
        f = FilterBuilder.build(SearchFilter(note_title="My Research Note"))
        assert f is not None
        cond = f.must[0]
        assert cond.key == "note_title"
        assert cond.match.value == "My Research Note"

    def test_combined_filter_has_multiple_must_conditions(self):
        f = FilterBuilder.build(
            SearchFilter(tags=["ai"], note_id="hash", note_path="p.md", note_title="T")
        )
        assert f is not None
        assert len(f.must) == 4
        keys = {c.key for c in f.must}
        assert keys == {"tags", "note_id", "note_path", "note_title"}

    def test_none_fields_are_not_included(self):
        f = FilterBuilder.build(SearchFilter(tags=["ai"], note_id=None))
        assert f is not None
        assert len(f.must) == 1
        assert f.must[0].key == "tags"

    def test_empty_tags_list_is_not_included(self):
        # An empty list means "no tag filter" — should produce None
        f = FilterBuilder.build(SearchFilter(tags=[]))
        assert f is None


# ── QdrantService.ensure_collection ──────────────────────────────────────────


class TestEnsureCollection:
    async def test_creates_collection_when_not_exists(self):
        svc, client = _make_service()
        await svc.ensure_collection()
        client.create_collection.assert_awaited_once()
        call_kwargs = client.create_collection.call_args.kwargs
        assert call_kwargs["collection_name"] == "test_col"

    async def test_skips_creation_when_collection_exists(self):
        svc, client = _make_service()
        client.collection_exists = AsyncMock(return_value=True)
        await svc.ensure_collection()
        client.create_collection.assert_not_awaited()

    async def test_payload_indexes_created_after_new_collection(self):
        svc, client = _make_service()
        await svc.ensure_collection()
        assert client.create_payload_index.await_count == len(_KEYWORD_INDEXES) + len(
            _INTEGER_INDEXES
        )

    async def test_payload_indexes_not_created_when_collection_exists(self):
        svc, client = _make_service()
        client.collection_exists = AsyncMock(return_value=True)
        await svc.ensure_collection()
        client.create_payload_index.assert_not_awaited()

    async def test_keyword_index_fields_match_constants(self):
        svc, client = _make_service()
        await svc.ensure_collection()
        indexed_fields = {
            c.kwargs["field_name"] for c in client.create_payload_index.call_args_list
        }
        for field in _KEYWORD_INDEXES:
            assert field in indexed_fields

    async def test_vector_params_use_cosine_distance(self):
        svc, client = _make_service()
        await svc.ensure_collection()
        vec_cfg = client.create_collection.call_args.kwargs["vectors_config"]
        assert vec_cfg.distance == qmodels.Distance.COSINE

    async def test_vector_size_passed_correctly(self):
        client = _make_client()
        svc = QdrantService(client=client, collection_name="col", vector_size=768)
        await svc.ensure_collection()
        vec_cfg = client.create_collection.call_args.kwargs["vectors_config"]
        assert vec_cfg.size == 768


# ── QdrantService.upsert ──────────────────────────────────────────────────────


class TestUpsert:
    async def test_empty_payloads_skips_call(self):
        svc, client = _make_service()
        await svc.upsert([], [])
        client.upsert.assert_not_awaited()

    async def test_single_payload_creates_correct_point(self):
        svc, client = _make_service()
        p = _payload(chunk_id=_CHUNK_ID_1, chunk_text="hello")
        await svc.upsert([p], [[0.1, 0.2, 0.3, 0.4]])
        client.upsert.assert_awaited_once()
        points = client.upsert.call_args.kwargs["points"]
        assert len(points) == 1
        assert points[0].id == _to_point_id(_CHUNK_ID_1)
        assert points[0].vector == [0.1, 0.2, 0.3, 0.4]
        assert points[0].payload["chunk_text"] == "hello"

    async def test_chunk_text_stored_in_payload(self):
        svc, client = _make_service()
        p = _payload(chunk_text="[Note: N]\n\ncontent")
        await svc.upsert([p], [[1.0, 0.0, 0.0, 0.0]])
        payload_dict = client.upsert.call_args.kwargs["points"][0].payload
        assert payload_dict["chunk_text"] == "[Note: N]\n\ncontent"

    async def test_wait_is_true(self):
        svc, client = _make_service()
        await svc.upsert([_payload()], [[0.0, 0.0, 0.0, 0.0]])
        assert client.upsert.call_args.kwargs["wait"] is True

    async def test_multiple_payloads(self):
        svc, client = _make_service()
        chunk_ids = [_CHUNK_ID_1, _CHUNK_ID_2, _CHUNK_ID_3]
        payloads = [_payload(chunk_id=cid) for cid in chunk_ids]
        vectors = [[float(i)] * 4 for i in range(3)]
        await svc.upsert(payloads, vectors)
        points = client.upsert.call_args.kwargs["points"]
        assert len(points) == 3
        assert [p.id for p in points] == [_to_point_id(cid) for cid in chunk_ids]


# ── QdrantService.search ──────────────────────────────────────────────────────


class TestSearch:
    async def test_empty_result(self):
        svc, client = _make_service()
        results = await svc.search(query_vector=[1.0, 0.0, 0.0, 0.0])
        assert results == []

    async def test_scored_point_parsed_into_search_result(self):
        svc, client = _make_service()
        client.query_points = AsyncMock(
            return_value=MagicMock(points=[
                _scored_point("cid1", 0.95, {"chunk_text": "hello", "note_title": "N"})
            ])
        )
        results = await svc.search(query_vector=[1.0, 0.0, 0.0, 0.0])
        assert len(results) == 1
        r = results[0]
        assert isinstance(r, SearchResult)
        assert r.chunk_id == "cid1"
        assert r.score == 0.95
        assert r.chunk_text == "hello"
        assert r.payload["note_title"] == "N"

    async def test_limit_passed_to_client(self):
        svc, client = _make_service()
        await svc.search(query_vector=[0.0, 0.0, 0.0, 0.0], limit=5)
        assert client.query_points.call_args.kwargs["limit"] == 5

    async def test_zero_score_threshold_passes_none(self):
        svc, client = _make_service()
        await svc.search(query_vector=[0.0] * 4, score_threshold=0.0)
        assert client.query_points.call_args.kwargs["score_threshold"] is None

    async def test_positive_threshold_passed_through(self):
        svc, client = _make_service()
        await svc.search(query_vector=[0.0] * 4, score_threshold=0.7)
        assert client.query_points.call_args.kwargs["score_threshold"] == 0.7

    async def test_filter_translated_and_passed(self):
        svc, client = _make_service()
        sf = SearchFilter(note_id="hash123")
        await svc.search(query_vector=[0.0] * 4, filters=sf)
        qdrant_filter = client.query_points.call_args.kwargs["query_filter"]
        assert qdrant_filter is not None
        assert qdrant_filter.must[0].key == "note_id"

    async def test_no_filter_passes_none(self):
        svc, client = _make_service()
        await svc.search(query_vector=[0.0] * 4, filters=None)
        assert client.query_points.call_args.kwargs["query_filter"] is None

    async def test_with_payload_is_true(self):
        svc, client = _make_service()
        await svc.search(query_vector=[0.0] * 4)
        assert client.query_points.call_args.kwargs["with_payload"] is True

    async def test_missing_chunk_text_in_payload_defaults_to_empty_string(self):
        svc, client = _make_service()
        client.query_points = AsyncMock(return_value=MagicMock(points=[_scored_point("cid", 0.8, {"note_title": "N"})]))
        results = await svc.search(query_vector=[0.0] * 4)
        assert results[0].chunk_text == ""

    async def test_multiple_results_ordered_by_qdrant(self):
        svc, client = _make_service()
        client.query_points = AsyncMock(
            return_value=MagicMock(points=[
                _scored_point("c1", 0.9, {"chunk_text": "high"}),
                _scored_point("c2", 0.7, {"chunk_text": "mid"}),
                _scored_point("c3", 0.5, {"chunk_text": "low"}),
            ])
        )
        results = await svc.search(query_vector=[0.0] * 4)
        assert [r.chunk_id for r in results] == ["c1", "c2", "c3"]


# ── QdrantService.delete ──────────────────────────────────────────────────────


class TestDeletePoints:
    async def test_empty_list_no_call(self):
        svc, client = _make_service()
        await svc.delete_points([])
        client.delete.assert_not_awaited()

    async def test_ids_passed_as_point_ids_list(self):
        svc, client = _make_service()
        await svc.delete_points([_CHUNK_ID_1, _CHUNK_ID_2])
        selector = client.delete.call_args.kwargs["points_selector"]
        assert isinstance(selector, qmodels.PointIdsList)
        assert selector.points == [_to_point_id(_CHUNK_ID_1), _to_point_id(_CHUNK_ID_2)]

    async def test_wait_is_true(self):
        svc, client = _make_service()
        await svc.delete_points([_CHUNK_ID_1])
        assert client.delete.call_args.kwargs["wait"] is True


class TestDeleteByNoteId:
    async def test_uses_filter_selector(self):
        svc, client = _make_service()
        await svc.delete_by_note_id("hash123")
        selector = client.delete.call_args.kwargs["points_selector"]
        assert isinstance(selector, qmodels.FilterSelector)

    async def test_filter_matches_note_id(self):
        svc, client = _make_service()
        await svc.delete_by_note_id("hash123")
        selector = client.delete.call_args.kwargs["points_selector"]
        cond = selector.filter.must[0]
        assert cond.key == "note_id"
        assert cond.match.value == "hash123"

    async def test_wait_is_true(self):
        svc, client = _make_service()
        await svc.delete_by_note_id("hash")
        assert client.delete.call_args.kwargs["wait"] is True


# ── QdrantService.update_payload ──────────────────────────────────────────────


class TestUpdatePayload:
    async def test_set_payload_called_with_correct_args(self):
        svc, client = _make_service()
        await svc.update_payload("cid1", {"tags": ["new_tag"]})
        client.set_payload.assert_awaited_once_with(
            collection_name="test_col",
            payload={"tags": ["new_tag"]},
            points=["cid1"],
            wait=True,
        )

    async def test_multiple_fields_updated_at_once(self):
        svc, client = _make_service()
        updates = {"tags": ["x"], "note_title": "New Title"}
        await svc.update_payload("cid", updates)
        assert client.set_payload.call_args.kwargs["payload"] == updates

    async def test_wait_is_true(self):
        svc, client = _make_service()
        await svc.update_payload("cid", {"k": "v"})
        assert client.set_payload.call_args.kwargs["wait"] is True


# ── QdrantService.count ───────────────────────────────────────────────────────


class TestCount:
    async def test_returns_count_from_client(self):
        svc, client = _make_service()
        client.count = AsyncMock(return_value=MagicMock(count=42))
        result = await svc.count()
        assert result == 42

    async def test_exact_true_passed(self):
        svc, client = _make_service()
        await svc.count()
        assert client.count.call_args.kwargs["exact"] is True

    async def test_zero_count(self):
        svc, client = _make_service()
        client.count = AsyncMock(return_value=MagicMock(count=0))
        assert await svc.count() == 0


# ── QdrantService.get_collection_info ────────────────────────────────────────


class TestGetCollectionInfo:
    def _mock_collection_info(self, vectors_count=10, size=768, distance="Cosine", status="green"):
        info = MagicMock()
        info.vectors_count = vectors_count
        info.status = MagicMock()
        info.status.value = status
        info.config.params.vectors.size = size
        info.config.params.vectors.distance = MagicMock()
        info.config.params.vectors.distance.value = distance
        return info

    async def test_returns_collection_info_dataclass(self):
        svc, client = _make_service()
        client.get_collection = AsyncMock(return_value=self._mock_collection_info())
        result = await svc.get_collection_info()
        assert isinstance(result, CollectionInfo)

    async def test_vector_count_extracted(self):
        svc, client = _make_service()
        client.get_collection = AsyncMock(return_value=self._mock_collection_info(vectors_count=99))
        result = await svc.get_collection_info()
        assert result.vector_count == 99

    async def test_vector_size_extracted(self):
        svc, client = _make_service()
        client.get_collection = AsyncMock(return_value=self._mock_collection_info(size=768))
        result = await svc.get_collection_info()
        assert result.vector_size == 768

    async def test_distance_extracted(self):
        svc, client = _make_service()
        client.get_collection = AsyncMock(
            return_value=self._mock_collection_info(distance="Cosine")
        )
        result = await svc.get_collection_info()
        assert result.distance == "Cosine"

    async def test_status_extracted(self):
        svc, client = _make_service()
        client.get_collection = AsyncMock(
            return_value=self._mock_collection_info(status="green")
        )
        result = await svc.get_collection_info()
        assert result.status == "green"

    async def test_none_vectors_count_defaults_to_zero(self):
        svc, client = _make_service()
        client.get_collection = AsyncMock(
            return_value=self._mock_collection_info(vectors_count=None)
        )
        result = await svc.get_collection_info()
        assert result.vector_count == 0

    async def test_collection_name_set(self):
        svc, client = _make_service()
        client.get_collection = AsyncMock(return_value=self._mock_collection_info())
        result = await svc.get_collection_info()
        assert result.name == "test_col"


# ── QdrantService.delete_collection ──────────────────────────────────────────


class TestDeleteCollection:
    async def test_delete_collection_called(self):
        svc, client = _make_service()
        await svc.delete_collection()
        client.delete_collection.assert_awaited_once_with(collection_name="test_col")


# ── QdrantService.health ──────────────────────────────────────────────────────


class TestHealth:
    async def test_returns_true_when_reachable(self):
        svc, client = _make_service()
        assert await svc.health() is True

    async def test_returns_false_on_exception(self):
        svc, client = _make_service()
        client.get_collections = AsyncMock(side_effect=ConnectionError("down"))
        assert await svc.health() is False
