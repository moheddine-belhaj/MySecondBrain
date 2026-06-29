"""Unit tests for Ranker."""

import pytest

from app.services.retrieval.ranker import Ranker
from app.services.vector.models import SearchResult


def _result(chunk_id: str, score: float) -> SearchResult:
    return SearchResult(chunk_id=chunk_id, score=score, chunk_text="text", payload={})


class TestSortByScore:
    def test_sorts_descending(self):
        results = [_result("a", 0.5), _result("b", 0.9), _result("c", 0.1)]
        sorted_r = Ranker.sort_by_score(results)
        scores = [r.score for r in sorted_r]
        assert scores == sorted(scores, reverse=True)

    def test_already_sorted_unchanged(self):
        results = [_result("a", 0.9), _result("b", 0.7), _result("c", 0.3)]
        sorted_r = Ranker.sort_by_score(results)
        assert [r.chunk_id for r in sorted_r] == ["a", "b", "c"]

    def test_single_element(self):
        results = [_result("a", 0.5)]
        assert Ranker.sort_by_score(results) == results

    def test_empty_list(self):
        assert Ranker.sort_by_score([]) == []

    def test_stable_on_ties(self):
        results = [_result("a", 0.5), _result("b", 0.5)]
        sorted_r = Ranker.sort_by_score(results)
        assert len(sorted_r) == 2
        assert sorted_r[0].score == sorted_r[1].score

    def test_does_not_mutate_input(self):
        results = [_result("a", 0.3), _result("b", 0.9)]
        original_order = [r.chunk_id for r in results]
        Ranker.sort_by_score(results)
        assert [r.chunk_id for r in results] == original_order


class TestRrfFuse:
    def test_candidate_in_both_lists_ranked_higher(self):
        r_a = _result("a", 0.9)
        r_b = _result("b", 0.8)
        r_c = _result("c", 0.7)

        list1 = [r_a, r_b, r_c]        # vector ranking
        list2 = [r_b, r_a, r_c]        # keyword ranking: b > a > c

        fused = Ranker.rrf_fuse(list1, list2)
        # "a" rank1=1, rank2=2 → RRF higher than "c" rank1=3, rank2=3
        assert fused[0].chunk_id in ("a", "b")
        assert fused[-1].chunk_id == "c"

    def test_fuse_single_list_preserves_order(self):
        results = [_result("a", 0.9), _result("b", 0.7), _result("c", 0.5)]
        fused = Ranker.rrf_fuse(results)
        assert [r.chunk_id for r in fused] == ["a", "b", "c"]

    def test_fuse_returns_all_candidates(self):
        list1 = [_result("a", 0.9), _result("b", 0.8)]
        list2 = [_result("b", 0.9), _result("c", 0.7)]
        fused = Ranker.rrf_fuse(list1, list2)
        ids = {r.chunk_id for r in fused}
        assert ids == {"a", "b", "c"}

    def test_fuse_empty_lists(self):
        assert Ranker.rrf_fuse([]) == []
