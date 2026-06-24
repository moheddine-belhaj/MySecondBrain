"""Unit tests for Deduplicator."""

import pytest

from app.services.retrieval.deduplicator import Deduplicator
from app.services.vector.models import SearchResult


def _result(
    chunk_id: str,
    score: float,
    note_id: str = "note1",
    heading_path: list[str] | None = None,
) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        score=score,
        chunk_text="text",
        payload={
            "note_id": note_id,
            "heading_path": heading_path or [],
        },
    )


class TestDeduplicatorHeadingDedup:
    def test_unique_headings_all_kept(self):
        results = [
            _result("a", 0.9, heading_path=["H1", "S1"]),
            _result("b", 0.8, heading_path=["H1", "S2"]),
            _result("c", 0.7, heading_path=["H1", "S3"]),
        ]
        kept, removed = Deduplicator(max_per_note=10).deduplicate(results)
        assert len(kept) == 3
        assert removed == 0

    def test_duplicate_heading_keeps_first(self):
        results = [
            _result("a", 0.9, heading_path=["H1", "S1"]),
            _result("b", 0.7, heading_path=["H1", "S1"]),  # same heading, lower score
        ]
        kept, removed = Deduplicator(max_per_note=10).deduplicate(results)
        assert len(kept) == 1
        assert kept[0].chunk_id == "a"
        assert removed == 1

    def test_same_heading_different_notes_both_kept(self):
        results = [
            _result("a", 0.9, note_id="note1", heading_path=["H1"]),
            _result("b", 0.8, note_id="note2", heading_path=["H1"]),
        ]
        kept, removed = Deduplicator(max_per_note=10).deduplicate(results)
        assert len(kept) == 2
        assert removed == 0

    def test_empty_heading_path_deduped_per_note(self):
        results = [
            _result("a", 0.9, note_id="note1", heading_path=[]),
            _result("b", 0.8, note_id="note1", heading_path=[]),
        ]
        kept, removed = Deduplicator(max_per_note=10).deduplicate(results)
        assert len(kept) == 1
        assert removed == 1


class TestDeduplicatorNoteCap:
    def test_cap_limits_per_note(self):
        results = [
            _result("a", 0.9, note_id="note1", heading_path=["S1"]),
            _result("b", 0.8, note_id="note1", heading_path=["S2"]),
            _result("c", 0.7, note_id="note1", heading_path=["S3"]),
        ]
        kept, removed = Deduplicator(max_per_note=2).deduplicate(results)
        assert len(kept) == 2
        assert kept[0].chunk_id == "a"
        assert kept[1].chunk_id == "b"
        assert removed == 1

    def test_cap_one_per_note(self):
        results = [
            _result("a", 0.9, note_id="note1", heading_path=["S1"]),
            _result("b", 0.8, note_id="note1", heading_path=["S2"]),
        ]
        kept, removed = Deduplicator(max_per_note=1).deduplicate(results)
        assert len(kept) == 1
        assert removed == 1

    def test_cap_applied_across_different_notes(self):
        results = [
            _result("a", 0.9, note_id="note1", heading_path=["S1"]),
            _result("b", 0.85, note_id="note2", heading_path=["S1"]),
            _result("c", 0.8, note_id="note1", heading_path=["S2"]),
            _result("d", 0.75, note_id="note2", heading_path=["S2"]),
            _result("e", 0.7, note_id="note1", heading_path=["S3"]),
        ]
        kept, removed = Deduplicator(max_per_note=2).deduplicate(results)
        note_ids = [r.payload["note_id"] for r in kept]
        assert note_ids.count("note1") <= 2
        assert note_ids.count("note2") <= 2
        assert removed == 1  # only "e" exceeds note1 cap


class TestDeduplicatorEdgeCases:
    def test_empty_list(self):
        kept, removed = Deduplicator().deduplicate([])
        assert kept == []
        assert removed == 0

    def test_single_result(self):
        results = [_result("a", 0.9)]
        kept, removed = Deduplicator().deduplicate(results)
        assert len(kept) == 1
        assert removed == 0

    def test_no_duplicates_returns_all(self):
        results = [
            _result("a", 0.9, note_id="n1", heading_path=["S1"]),
            _result("b", 0.8, note_id="n2", heading_path=["S1"]),
            _result("c", 0.7, note_id="n3", heading_path=["S1"]),
        ]
        kept, removed = Deduplicator(max_per_note=5).deduplicate(results)
        assert len(kept) == 3
        assert removed == 0

    def test_removed_count_matches_difference(self):
        results = [_result(str(i), 1.0 - i * 0.1, note_id="note1", heading_path=[f"S{i}"]) for i in range(5)]
        kept, removed = Deduplicator(max_per_note=2).deduplicate(results)
        assert removed == len(results) - len(kept)
