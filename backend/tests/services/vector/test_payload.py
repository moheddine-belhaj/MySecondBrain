"""Unit tests for VectorPayload schema."""

import pytest

from app.services.vector.models import VectorPayload


def _payload(**overrides) -> VectorPayload:
    defaults = dict(
        chunk_id="abc123",
        note_id="note456",
        note_title="My Note",
        note_path="folder/my-note.md",
        tags=["ai", "research"],
        heading_path=["My Note", "Section One"],
        chunk_index=0,
        total_chunks=3,
        word_count=120,
        indexed_at="2024-01-01T00:00:00+00:00",
        note_modified_at="2023-12-01T10:00:00+00:00",
    )
    defaults.update(overrides)
    return VectorPayload(**defaults)


class TestVectorPayload:
    def test_to_dict_contains_all_fields(self):
        p = _payload()
        d = p.to_dict()
        assert set(d.keys()) == {
            "chunk_id",
            "note_id",
            "note_title",
            "note_path",
            "tags",
            "heading_path",
            "chunk_index",
            "total_chunks",
            "word_count",
            "indexed_at",
            "note_modified_at",
        }

    def test_to_dict_values_match_fields(self):
        p = _payload()
        d = p.to_dict()
        assert d["chunk_id"] == "abc123"
        assert d["note_id"] == "note456"
        assert d["note_title"] == "My Note"
        assert d["note_path"] == "folder/my-note.md"
        assert d["tags"] == ["ai", "research"]
        assert d["heading_path"] == ["My Note", "Section One"]
        assert d["chunk_index"] == 0
        assert d["total_chunks"] == 3
        assert d["word_count"] == 120
        assert d["indexed_at"] == "2024-01-01T00:00:00+00:00"
        assert d["note_modified_at"] == "2023-12-01T10:00:00+00:00"

    def test_empty_tags_and_headings(self):
        p = _payload(tags=[], heading_path=[])
        d = p.to_dict()
        assert d["tags"] == []
        assert d["heading_path"] == []

    def test_to_dict_returns_new_dict_each_call(self):
        p = _payload()
        d1 = p.to_dict()
        d2 = p.to_dict()
        assert d1 == d2
        assert d1 is not d2

    def test_chunk_index_zero_allowed(self):
        p = _payload(chunk_index=0)
        assert p.to_dict()["chunk_index"] == 0

    def test_large_word_count(self):
        p = _payload(word_count=10_000)
        assert p.to_dict()["word_count"] == 10_000

    def test_nested_heading_path(self):
        path = ["Root", "Chapter 1", "Section 1.1", "Sub-section"]
        p = _payload(heading_path=path)
        assert p.to_dict()["heading_path"] == path
