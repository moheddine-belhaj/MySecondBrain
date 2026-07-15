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


class TestWeightedRrfFuse:
    def test_higher_weight_list_has_more_influence(self):
        # c1 ranks first in list A (weight=0.9), last in list B (weight=0.1)
        # c2 ranks first in list B, last in list A
        c1 = _result("c1", 0.9)
        c2 = _result("c2", 0.9)
        list_a = [c1, c2]   # c1 > c2
        list_b = [c2, c1]   # c2 > c1

        fused = Ranker.weighted_rrf_fuse([(list_a, 0.9), (list_b, 0.1)])
        # list_a dominates → c1 should win
        assert fused[0].chunk_id == "c1"

    def test_equal_weights_same_as_rrf_fuse(self):
        r_a = _result("a", 0.9)
        r_b = _result("b", 0.7)
        r_c = _result("c", 0.5)
        list1 = [r_a, r_b, r_c]
        list2 = [r_b, r_a, r_c]

        equal_weight = Ranker.weighted_rrf_fuse([(list1, 1.0), (list2, 1.0)])
        rrf = Ranker.rrf_fuse(list1, list2)
        assert [r.chunk_id for r in equal_weight] == [r.chunk_id for r in rrf]

    def test_union_of_both_lists_returned(self):
        list_a = [_result("a", 0.9), _result("b", 0.7)]
        list_b = [_result("b", 0.9), _result("c", 0.6)]
        fused = Ranker.weighted_rrf_fuse([(list_a, 0.5), (list_b, 0.5)])
        ids = {r.chunk_id for r in fused}
        assert ids == {"a", "b", "c"}

    def test_doc_in_both_lists_outranks_doc_in_one(self):
        shared = _result("shared", 0.8)
        only_a = _result("only_a", 0.9)
        only_b = _result("only_b", 0.9)
        filler = _result("filler", 0.1)
        # 3-item lists: "shared" is rank 2 in both; "only_a/b" are rank 1 in one list.
        # With k=60, n=3: shared score = 2×0.5/(60+2)=1/62≈0.01613
        # only_a score = 0.5/(60+1)+0.5/(60+4)=0.5/61+0.5/64≈0.01601 < shared
        list_a = [only_a, shared, filler]
        list_b = [only_b, shared, filler]

        fused = Ranker.weighted_rrf_fuse([(list_a, 0.5), (list_b, 0.5)])
        shared_rank = next(i for i, r in enumerate(fused) if r.chunk_id == "shared")
        only_a_rank = next(i for i, r in enumerate(fused) if r.chunk_id == "only_a")
        only_b_rank = next(i for i, r in enumerate(fused) if r.chunk_id == "only_b")
        assert shared_rank < only_a_rank
        assert shared_rank < only_b_rank

    def test_scores_in_result_are_rrf_scores_not_originals(self):
        results = Ranker.weighted_rrf_fuse([([_result("a", 0.99)], 0.7)])
        assert results[0].score != 0.99  # RRF score, not original cosine

    def test_scores_are_positive(self):
        list_a = [_result("a", 0.9), _result("b", 0.5)]
        results = Ranker.weighted_rrf_fuse([(list_a, 0.7)])
        assert all(r.score > 0 for r in results)

    def test_empty_input_returns_empty(self):
        assert Ranker.weighted_rrf_fuse([]) == []

    def test_single_list_preserves_relative_order(self):
        results = [_result("a", 0.9), _result("b", 0.7), _result("c", 0.5)]
        fused = Ranker.weighted_rrf_fuse([(results, 1.0)])
        assert [r.chunk_id for r in fused] == ["a", "b", "c"]
