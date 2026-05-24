"""VectorRepository — abstract contract for vector storage backends.

Why an ABC here instead of a Protocol?
---------------------------------------
Protocol gives structural ("duck") typing — any class with the right methods
qualifies. ABC gives nominal typing — you must explicitly subclass and
implement every @abstractmethod, and mypy/IDE catches missing methods at
class-definition time rather than at the call site.

For swappable infrastructure (Qdrant → Pinecone → pgvector), nominal typing
is safer: a half-implemented adapter fails loudly at import, not silently at
the first search call in production.

Adding a new backend:
    1. Subclass VectorRepository.
    2. Implement all abstract methods.
    3. Update main.py lifespan to instantiate your class.
    4. Zero changes to endpoints or EmbeddingPipeline required.
"""

from abc import ABC, abstractmethod

from app.services.vector.models import (
    CollectionInfo,
    SearchFilter,
    SearchResult,
    VectorPayload,
)


class VectorRepository(ABC):
    """Contract for any vector storage backend."""

    # ── Collection lifecycle ───────────────────────────────────────────────────

    @abstractmethod
    async def ensure_collection(self) -> None:
        """Create the collection (and its payload indexes) if it does not exist.
        Must be idempotent — safe to call on every startup.
        """
        ...

    @abstractmethod
    async def delete_collection(self) -> None:
        """Permanently drop the collection and all its data.
        Useful for full re-index or test teardown.
        """
        ...

    # ── Write ──────────────────────────────────────────────────────────────────

    @abstractmethod
    async def upsert(
        self,
        payloads: list[VectorPayload],
        vectors: list[list[float]],
    ) -> None:
        """Write (payload, vector) pairs. Overwrites any existing point with
        the same chunk_id. `payloads` and `vectors` must be the same length.
        """
        ...

    @abstractmethod
    async def update_payload(self, chunk_id: str, updates: dict) -> None:
        """Patch a point's metadata fields without touching its vector.

        Only the keys present in `updates` are changed; existing fields not
        in `updates` are left untouched. Use this to re-tag notes or correct
        metadata after a vault edit that doesn't change chunk boundaries.
        """
        ...

    # ── Read ───────────────────────────────────────────────────────────────────

    @abstractmethod
    async def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        score_threshold: float = 0.0,
        filters: SearchFilter | None = None,
    ) -> list[SearchResult]:
        """Return the top-`limit` most similar points.

        `score_threshold` excludes results below this cosine similarity.
        `filters`         restricts the search space before scoring (ANN).
        Results are ordered descending by score.
        """
        ...

    @abstractmethod
    async def get_all_point_ids(self) -> set[str]:
        """Return every point ID in the collection (used for stale-chunk pruning)."""
        ...

    @abstractmethod
    async def count(self) -> int:
        """Return the exact number of indexed points."""
        ...

    @abstractmethod
    async def get_collection_info(self) -> CollectionInfo:
        """Return configuration and status of the collection."""
        ...

    # ── Delete ─────────────────────────────────────────────────────────────────

    @abstractmethod
    async def delete_points(self, ids: list[str]) -> None:
        """Delete specific points by chunk ID. No-op for an empty list."""
        ...

    @abstractmethod
    async def delete_by_note_id(self, note_id: str) -> None:
        """Delete all chunks belonging to a note in a single filter-based call.

        More efficient than fetching IDs then deleting — avoids the extra
        scroll round-trip when the caller only has the note_id.
        """
        ...

    # ── Health ─────────────────────────────────────────────────────────────────

    @abstractmethod
    async def health(self) -> bool:
        """Return True if the backend is reachable and serving requests."""
        ...
