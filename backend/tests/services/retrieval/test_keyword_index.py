"""Unit tests for KeywordIndex (BM25 in-process search)."""

import pytest

from app.services.retrieval.keyword_index import KeywordIndex, tokenize


# ── tokenize ──────────────────────────────────────────────────────────────────

class TestTokenize:
    def test_lowercases(self):
        assert "python" in tokenize("Python")

    def test_removes_stop_words(self):
        tokens = tokenize("the cat and a dog")
        assert "the" not in tokens
        assert "and" not in tokens
        assert "a" not in tokens

    def test_removes_single_char_tokens(self):
        assert "x" not in tokenize("x y z python")

    def test_keeps_technical_terms(self):
        tokens = tokenize("asyncio event loop BM25")
        assert "asyncio" in tokens
        assert "bm25" in tokens
        assert "event" in tokens
        assert "loop" in tokens

    def test_handles_numbers(self):
        assert "bm25" in tokenize("BM25 ranking")

    def test_empty_string(self):
        assert tokenize("") == []

    def test_all_stop_words(self):
        assert tokenize("the and or but") == []

    def test_consistent_at_build_and_query_time(self):
        text = "Python asyncio event loop"
        assert tokenize(text) == tokenize(text.upper())


# ── KeywordIndex.build ────────────────────────────────────────────────────────

class TestKeywordIndexBuild:
    def test_starts_stale(self):
        idx = KeywordIndex()
        assert idx.is_stale is True

    def test_not_stale_after_build(self):
        idx = KeywordIndex()
        idx.build([("c1", {"chunk_text": "python asyncio event loop"})])
        assert idx.is_stale is False

    def test_corpus_size_after_build(self):
        idx = KeywordIndex()
        entries = [
            ("c1", {"chunk_text": "python asyncio"}),
            ("c2", {"chunk_text": "rust memory safety"}),
        ]
        idx.build(entries)
        assert idx.corpus_size == 2

    def test_build_empty_corpus_clears_index(self):
        idx = KeywordIndex()
        idx.build([("c1", {"chunk_text": "python"})])
        idx.build([])
        assert idx.corpus_size == 0
        assert idx.is_stale is False

    def test_rebuild_replaces_previous(self):
        idx = KeywordIndex()
        idx.build([("c1", {"chunk_text": "python asyncio"})])
        # Rebuild with 3 docs so "rust" has positive IDF (N=3, df=1 → log(2.5/1.5) > 0)
        idx.build([
            ("c2", {"chunk_text": "rust memory safety"}),
            ("c3", {"chunk_text": "go programming language"}),
            ("c4", {"chunk_text": "java enterprise application"}),
        ])
        assert idx.corpus_size == 3
        results = idx.search("rust", limit=5)
        assert results[0].chunk_id == "c2"

    def test_missing_chunk_text_treated_as_empty(self):
        # Docs with no text tokenize to [] — BM25Okapi would ZeroDivide if all are empty
        idx = KeywordIndex()
        idx.build([("c1", {}), ("c2", {}), ("c3", {})])
        assert idx.corpus_size == 3
        results = idx.search("anything", limit=5)
        assert results == []


# ── KeywordIndex.search ───────────────────────────────────────────────────────

class TestKeywordIndexSearch:
    # BM25 note: rank_bm25's IDF = log((N-df+0.5)/(df+0.5)). With N=2, df=1, IDF=0.
    # Need N≥3 with df=1 to get positive IDF, so every corpus below has 3+ docs.

    def _build(self, texts: dict[str, str]) -> KeywordIndex:
        idx = KeywordIndex()
        idx.build([(cid, {"chunk_text": text}) for cid, text in texts.items()])
        return idx

    def _build3(self, main: tuple[str, str]) -> KeywordIndex:
        """Build a 3-doc corpus; main doc has the unique term, two distractors don't."""
        cid, text = main
        return self._build({
            cid: text,
            "_d1": "unrelated topic about databases",
            "_d2": "another unrelated document about networking",
        })

    def test_exact_match_returned(self):
        idx = self._build3(("c1", "python asyncio event loop"))
        results = idx.search("asyncio", limit=5)
        assert any(r.chunk_id == "c1" for r in results)

    def test_no_match_returns_empty(self):
        idx = self._build3(("c1", "python asyncio"))
        results = idx.search("rust", limit=5)
        assert results == []

    def test_most_relevant_ranked_first(self):
        # c1 mentions asyncio 3× → higher TF → higher BM25 score than c2
        idx = self._build({
            "c1": "asyncio asyncio asyncio event loop",
            "c2": "asyncio once mentioned here",
            "_d": "unrelated databases networking systems",
        })
        results = idx.search("asyncio", limit=5)
        assert results[0].chunk_id == "c1"

    def test_limit_respected(self):
        idx = self._build({
            "c1": "python asyncio event",
            "c2": "python asyncio loop",
            "c3": "python asyncio coroutine",
            "_d": "unrelated databases networking",
        })
        results = idx.search("asyncio", limit=2)
        assert len(results) <= 2

    def test_scores_are_positive(self):
        idx = self._build3(("c1", "python asyncio event loop"))
        results = idx.search("asyncio", limit=5)
        assert all(r.score > 0 for r in results)

    def test_result_has_chunk_text(self):
        idx = self._build3(("c1", "python asyncio event loop"))
        results = idx.search("asyncio", limit=5)
        matched = next(r for r in results if r.chunk_id == "c1")
        assert matched.chunk_text == "python asyncio event loop"

    def test_result_has_full_payload(self):
        idx = KeywordIndex()
        idx.build([
            ("c1", {"chunk_text": "asyncio event", "note_title": "My Note", "tags": ["python"]}),
            ("_d1", {"chunk_text": "unrelated databases topic"}),
            ("_d2", {"chunk_text": "networking systems overview"}),
        ])
        results = idx.search("asyncio", limit=5)
        matched = next(r for r in results if r.chunk_id == "c1")
        assert matched.payload["note_title"] == "My Note"
        assert matched.payload["tags"] == ["python"]

    def test_stop_word_only_query_returns_empty(self):
        idx = self._build3(("c1", "python asyncio"))
        results = idx.search("the and or", limit=5)
        assert results == []

    def test_empty_query_returns_empty(self):
        idx = self._build3(("c1", "python asyncio"))
        results = idx.search("", limit=5)
        assert results == []

    def test_search_on_empty_corpus_returns_empty(self):
        idx = KeywordIndex()
        idx.build([])
        results = idx.search("python", limit=5)
        assert results == []

    def test_search_before_build_returns_empty(self):
        idx = KeywordIndex()
        results = idx.search("python", limit=5)
        assert results == []

    def test_rare_term_beats_common_term(self):
        # "bm25" appears only in c2 → unique → high IDF
        idx = self._build({
            "c1": "asyncio asyncio event loop",
            "c2": "bm25 ranking formula scoring",
            "_d": "unrelated topic about systems",
        })
        results_bm25 = idx.search("bm25", limit=5)
        assert results_bm25[0].chunk_id == "c2"


# ── KeywordIndex.invalidate ───────────────────────────────────────────────────

class TestKeywordIndexInvalidate:
    def test_invalidate_marks_stale(self):
        idx = KeywordIndex()
        idx.build([("c1", {"chunk_text": "python"})])
        assert idx.is_stale is False
        idx.invalidate()
        assert idx.is_stale is True

    def test_search_still_works_after_invalidate(self):
        idx = KeywordIndex()
        idx.build([
            ("c1", {"chunk_text": "python asyncio event loop"}),
            ("_d1", {"chunk_text": "unrelated databases topic"}),
            ("_d2", {"chunk_text": "networking systems overview"}),
        ])
        idx.invalidate()
        # search uses the in-memory snapshot even when stale
        results = idx.search("asyncio", limit=5)
        assert len(results) >= 1

    def test_invalidate_before_build_no_error(self):
        idx = KeywordIndex()
        idx.invalidate()
        assert idx.is_stale is True
