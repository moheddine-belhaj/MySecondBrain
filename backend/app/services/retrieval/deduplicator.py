"""Deduplicator — removes near-duplicate chunks from a ranked candidate list.

Two strategies applied in order on the already-score-sorted input:

1. Heading dedup
   Chunks with the same (note_id, heading_path) are adjacent sections of the
   same note heading. Returning several of them adds noise without new context.
   Keep the first (highest-scoring) one; discard the rest.

2. Per-note cap
   After heading dedup, limit how many chunks from a single note_id appear in
   the final result. Default max_per_note=2 lets a very relevant note contribute
   two distinct sections while preventing it from flooding the top-k.

Both strategies are only applied when the engine is called with deduplicate=True.
The input list must be sorted by score descending before calling deduplicate().

Future extension: semantic dedup via cosine similarity between chunk vectors
would catch near-duplicates across different headings. Deferred until we have
evidence that heading+note-cap misses real cases.
"""

import logging

from app.services.vector.models import SearchResult

logger = logging.getLogger("app.services.retrieval.deduplicator")


class Deduplicator:
    def __init__(self, max_per_note: int = 2) -> None:
        self._max_per_note = max_per_note

    def deduplicate(
        self, results: list[SearchResult]
    ) -> tuple[list[SearchResult], int]:
        """Return (kept, removed_count).

        Iterates once through the score-sorted list. The first occurrence of
        each (note_id, heading_path) key wins; all later ones are dropped.
        Then the per-note cap is applied on the already-heading-deduped list.
        """
        kept = self._heading_dedup(results)
        kept = self._note_cap(kept)
        removed = len(results) - len(kept)
        logger.debug(
            "Dedup complete",
            extra={"input": len(results), "kept": len(kept), "removed": removed},
        )
        return kept, removed

    def _heading_dedup(self, results: list[SearchResult]) -> list[SearchResult]:
        seen: set[tuple[str, tuple[str, ...]]] = set()
        out: list[SearchResult] = []
        for r in results:
            note_id = r.payload.get("note_id", "")
            heading_path = tuple(r.payload.get("heading_path", []))
            key = (note_id, heading_path)
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
        return out

    def _note_cap(self, results: list[SearchResult]) -> list[SearchResult]:
        counts: dict[str, int] = {}
        out: list[SearchResult] = []
        for r in results:
            note_id = r.payload.get("note_id", "")
            n = counts.get(note_id, 0)
            if n >= self._max_per_note:
                continue
            counts[note_id] = n + 1
            out.append(r)
        return out
