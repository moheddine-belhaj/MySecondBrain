"""KeywordIndex — in-memory BM25 over the chunk corpus.

Built from a Qdrant scroll on the first hybrid or keyword search, then
reused across all requests. After ingest or sync, call invalidate() so the
next search triggers a rebuild with the updated corpus.

Why BM25?
---------
BM25 (Best Match 25) is the industry-standard term-frequency ranking function
behind Elasticsearch and Solr. It handles:
  - Term saturation: extra occurrences of a term add diminishing returns.
  - Document-length normalisation: short chunks aren't penalised vs long ones.
  - IDF: rare terms (e.g. "asyncio") score higher than common ones ("the").

For a personal vault, building and querying BM25 over all chunks takes <100ms,
so an in-process in-memory index is perfectly adequate.

Tokenizer
---------
Word-boundary regex + lowercase + stop-word filter. Simple enough for personal
notes (English-heavy), fast enough to tokenize 10k chunks in <50ms.

Thread safety
-------------
`build()` is designed to be called from `asyncio.to_thread()` — it holds a
`threading.Lock` around all state mutations. Concurrent `search()` calls are
fine: they take a snapshot of the current BM25 reference under the lock, then
release immediately.
"""

import logging
import re
import threading

from rank_bm25 import BM25Okapi

from app.services.vector.models import SearchResult

logger = logging.getLogger("app.services.retrieval.keyword_index")

_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "that", "this", "it", "its", "i", "you",
    "he", "she", "we", "they", "not", "no", "as", "from", "into", "about",
    "if", "then", "so", "also", "just", "than", "more", "can", "their",
    "there", "when", "which", "who", "what", "how", "all", "any", "each",
    "up", "out", "use", "used", "using", "new", "one", "two", "get", "set",
})


def tokenize(text: str) -> list[str]:
    """Lowercase word-boundary tokenizer with stop-word removal.

    Exported so callers can tokenize queries with the same function used
    at index-build time (consistent vocabulary).
    """
    tokens = re.findall(r"\b[a-z0-9]+\b", text.lower())
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]


class KeywordIndex:
    """Thread-safe in-memory BM25 index over all chunk texts.

    Lifecycle:
      build(entries)   — called after ingest or sync (from a thread via asyncio.to_thread)
      search(query, n) — called by the engine per request
      invalidate()     — marks stale; next search will trigger a rebuild
    """

    def __init__(self) -> None:
        self._bm25: BM25Okapi | None = None
        self._chunk_ids: list[str] = []
        self._payloads: dict[str, dict] = {}
        self._stale: bool = True
        self._lock = threading.Lock()

    def build(self, entries: list[tuple[str, dict]]) -> None:
        """(Re)build the BM25 index from (chunk_id, payload) pairs.

        `payload` must contain at least `chunk_text`. All fields are stored
        so `search()` can return fully-populated SearchResult objects without
        a Qdrant round-trip.
        """
        if not entries:
            with self._lock:
                self._bm25 = None
                self._chunk_ids = []
                self._payloads = {}
                self._stale = False
            logger.info("KeywordIndex: corpus empty — index cleared")
            return

        chunk_ids = [cid for cid, _ in entries]
        payloads = {cid: payload for cid, payload in entries}
        tokenized = [tokenize(payload.get("chunk_text", "")) for _, payload in entries]
        bm25 = BM25Okapi(tokenized)

        with self._lock:
            self._bm25 = bm25
            self._chunk_ids = chunk_ids
            self._payloads = payloads
            self._stale = False

        logger.info("KeywordIndex: built", extra={"corpus_size": len(chunk_ids)})

    def search(self, query: str, limit: int) -> list[SearchResult]:
        """Score all chunks against query, return top-`limit` results.

        Returns an empty list when the index is empty or the query produces
        no tokens after stop-word removal.
        """
        with self._lock:
            bm25 = self._bm25
            chunk_ids = list(self._chunk_ids)
            payloads = self._payloads

        if bm25 is None or not chunk_ids:
            return []

        tokens = tokenize(query)
        if not tokens:
            return []

        raw_scores = bm25.get_scores(tokens)

        # pair (index, score), filter zero-score, sort descending
        scored = [(i, float(raw_scores[i])) for i in range(len(chunk_ids)) if raw_scores[i] > 0]
        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:limit]

        results: list[SearchResult] = []
        for idx, score in top:
            cid = chunk_ids[idx]
            payload = payloads.get(cid, {})
            results.append(SearchResult(
                chunk_id=cid,
                score=score,
                chunk_text=payload.get("chunk_text", ""),
                payload=payload,
            ))
        return results

    def invalidate(self) -> None:
        """Mark the index stale. The next search call triggers a rebuild."""
        with self._lock:
            self._stale = True
        logger.debug("KeywordIndex: invalidated")

    @property
    def is_stale(self) -> bool:
        with self._lock:
            return self._stale

    @property
    def corpus_size(self) -> int:
        with self._lock:
            return len(self._chunk_ids)
