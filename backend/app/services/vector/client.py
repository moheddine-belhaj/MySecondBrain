"""QdrantService — concrete VectorRepository backed by Qdrant.

Implements every method of the VectorRepository ABC.

Architecture notes
------------------
- Uses AsyncQdrantClient (HTTP, not gRPC) — no extra protobuf dependency;
  connection pooling is handled by httpx internally.
- Created once in main.py lifespan and stored on app.state; injected into
  endpoints via the QdrantDep type alias in dependencies.py.
- All methods are async — no blocking I/O on the event loop.
- ensure_collection() is idempotent: no-op if the collection already exists,
  so it is safe to call on every startup or before every ingest run.
- Payload indexes are created once, right after collection creation.
  They dramatically speed up metadata filters at scale (Qdrant uses them for
  pre-filtering before the ANN search instead of scanning all points).

Payload indexes created
-----------------------
  tags        — keyword (enables "has any of these tags" filtering)
  note_id     — keyword (exact hash match, used by delete_by_note_id + search)
  note_path   — keyword (exact path match)
  note_title  — keyword (exact title match)
  chunk_index — integer (supports range queries if needed)
"""

import logging
import uuid as _uuid

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from app.services.vector.filters import FilterBuilder
from app.services.vector.models import (
    CollectionInfo,
    SearchFilter,
    SearchResult,
    VectorPayload,
)
from app.services.vector.repository import VectorRepository

logger = logging.getLogger("app.services.vector")

# Fields that get a Qdrant payload index for fast filtering.
_KEYWORD_INDEXES = ("tags", "note_id", "note_path", "note_title")
_INTEGER_INDEXES = ("chunk_index",)


def _to_point_id(chunk_id: str) -> str:
    """Convert a 64-char SHA-256 hex digest to a UUID string.

    Qdrant only accepts unsigned integers or UUID-formatted strings as point IDs.
    We take the first 128 bits (32 hex chars) of the SHA-256 and format them as
    a UUID. The full SHA-256 is preserved in the payload under 'chunk_id'.
    """
    return str(_uuid.UUID(hex=chunk_id[:32]))


class QdrantService(VectorRepository):
    def __init__(
        self,
        client: AsyncQdrantClient,
        collection_name: str,
        vector_size: int,
    ) -> None:
        self._client = client
        self._collection = collection_name
        self._vector_size = vector_size

    # ── Collection lifecycle ───────────────────────────────────────────────────

    async def ensure_collection(self) -> None:
        """Create the collection + payload indexes if they do not yet exist."""
        exists = await self._client.collection_exists(self._collection)
        if exists:
            logger.debug("Collection already exists", extra={"collection": self._collection})
            return

        await self._client.create_collection(
            collection_name=self._collection,
            vectors_config=qmodels.VectorParams(
                size=self._vector_size,
                distance=qmodels.Distance.COSINE,
            ),
        )
        logger.info(
            "Collection created",
            extra={
                "collection": self._collection,
                "vector_size": self._vector_size,
                "distance": "cosine",
            },
        )
        await self._create_payload_indexes()

    async def delete_collection(self) -> None:
        await self._client.delete_collection(collection_name=self._collection)
        logger.info("Collection deleted", extra={"collection": self._collection})

    async def _create_payload_indexes(self) -> None:
        """Create keyword + integer indexes on filterable payload fields.

        Called once after collection creation. Qdrant uses these to pre-filter
        candidate points before running the ANN scan — essential for queries
        like "find top-10 chunks tagged 'python' that are similar to this vector".
        Without indexes, Qdrant falls back to a full payload scan on every query.
        """
        for field_name in _KEYWORD_INDEXES:
            await self._client.create_payload_index(
                collection_name=self._collection,
                field_name=field_name,
                field_schema=qmodels.PayloadSchemaType.KEYWORD,
            )
        for field_name in _INTEGER_INDEXES:
            await self._client.create_payload_index(
                collection_name=self._collection,
                field_name=field_name,
                field_schema=qmodels.PayloadSchemaType.INTEGER,
            )
        logger.debug(
            "Payload indexes created",
            extra={"fields": list(_KEYWORD_INDEXES) + list(_INTEGER_INDEXES)},
        )

    # ── Write ──────────────────────────────────────────────────────────────────

    async def upsert(
        self,
        payloads: list[VectorPayload],
        vectors: list[list[float]],
    ) -> None:
        """Upsert (payload, vector) pairs. Overwrites any point with the same chunk_id.

        `wait=True` blocks until Qdrant confirms the write is durable,
        giving callers a reliable success signal before reporting IndexingStats.
        """
        if not payloads:
            return

        points = [
            qmodels.PointStruct(
                id=_to_point_id(p.chunk_id),
                vector=v,
                payload=p.to_dict(),
            )
            for p, v in zip(payloads, vectors)
        ]

        await self._client.upsert(
            collection_name=self._collection,
            points=points,
            wait=True,
        )
        logger.debug("Upserted points", extra={"count": len(points)})

    async def update_payload(self, chunk_id: str, updates: dict) -> None:
        """Patch specific payload fields without touching the vector.

        Only keys present in `updates` are written; other fields are preserved.
        Use this for metadata corrections (re-tagging, path renames) that
        don't change chunk content and don't require re-embedding.
        """
        await self._client.set_payload(
            collection_name=self._collection,
            payload=updates,
            points=[chunk_id],
            wait=True,
        )
        logger.debug("Payload updated", extra={"chunk_id": chunk_id, "keys": list(updates)})

    # ── Read ───────────────────────────────────────────────────────────────────

    async def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        score_threshold: float = 0.0,
        filters: SearchFilter | None = None,
    ) -> list[SearchResult]:
        """Return the top-`limit` most similar chunks.

        Qdrant applies the filter as a pre-filter (using the payload indexes)
        before the ANN scan, so filtering is cheap even at scale.

        `score_threshold=0.0` (the default) means no threshold — all results
        down to the lowest similarity score are returned up to `limit`.
        """
        qdrant_filter = FilterBuilder.build(filters)
        threshold = score_threshold if score_threshold > 0.0 else None

        response = await self._client.query_points(
            collection_name=self._collection,
            query=query_vector,
            query_filter=qdrant_filter,
            limit=limit,
            score_threshold=threshold,
            with_payload=True,
            with_vectors=False,
        )

        results = [
            SearchResult(
                chunk_id=(p.payload or {}).get("chunk_id", str(p.id)),
                score=p.score,
                chunk_text=(p.payload or {}).get("chunk_text", ""),
                payload=p.payload or {},
            )
            for p in response.points
        ]

        logger.debug(
            "Search complete",
            extra={"hits": len(results), "limit": limit, "threshold": score_threshold},
        )
        return results

    async def get_all_point_ids(self) -> set[str]:
        """Scroll through all points and collect their IDs.

        Used by EmbeddingPipeline for stale-chunk detection (existing − new = stale).
        For collections with >100k points a streaming approach would be more
        memory-efficient, but that is out of scope for this task.
        """
        ids: set[str] = set()
        offset = None

        while True:
            results, next_offset = await self._client.scroll(
                collection_name=self._collection,
                limit=1000,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in results:
                chunk_id = (point.payload or {}).get("chunk_id")
                if chunk_id:
                    ids.add(chunk_id)
            if next_offset is None:
                break
            offset = next_offset

        logger.debug("Fetched all point IDs", extra={"count": len(ids)})
        return ids

    async def count(self) -> int:
        """Return exact point count (Qdrant's exact=True avoids approximate counting)."""
        result = await self._client.count(
            collection_name=self._collection,
            exact=True,
        )
        return result.count

    async def get_collection_info(self) -> CollectionInfo:
        """Fetch collection configuration and status from Qdrant."""
        info = await self._client.get_collection(collection_name=self._collection)

        vectors_count = info.vectors_count or 0

        # When created with a single VectorParams (not named vectors), the
        # config.params.vectors field is directly a VectorParams object.
        vec_cfg = info.config.params.vectors
        vector_size = vec_cfg.size if hasattr(vec_cfg, "size") else self._vector_size
        distance = vec_cfg.distance.value if hasattr(vec_cfg, "distance") else "Cosine"

        return CollectionInfo(
            name=self._collection,
            vector_count=vectors_count,
            vector_size=vector_size,
            distance=distance,
            status=str(info.status.value) if hasattr(info.status, "value") else str(info.status),
        )

    # ── Delete ─────────────────────────────────────────────────────────────────

    async def delete_points(self, ids: list[str]) -> None:
        """Delete a list of points by chunk ID. No-op for an empty list."""
        if not ids:
            return

        await self._client.delete(
            collection_name=self._collection,
            points_selector=qmodels.PointIdsList(points=[_to_point_id(i) for i in ids]),
            wait=True,
        )
        logger.info("Deleted points by ID", extra={"count": len(ids)})

    async def delete_by_note_id(self, note_id: str) -> None:
        """Delete every chunk belonging to a note using a single filter-based call.

        More efficient than the scroll-then-delete pattern when you only have
        the note_id — avoids a full scroll round-trip.
        Requires the `note_id` payload index (created by ensure_collection).
        """
        await self._client.delete(
            collection_name=self._collection,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="note_id",
                            match=qmodels.MatchValue(value=note_id),
                        )
                    ]
                )
            ),
            wait=True,
        )
        logger.info("Deleted points by note_id", extra={"note_id": note_id})

    # ── Health ─────────────────────────────────────────────────────────────────

    async def health(self) -> bool:
        try:
            await self._client.get_collections()
            return True
        except Exception:
            return False
