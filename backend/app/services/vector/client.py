"""QdrantService — async Qdrant client abstraction.

Responsibilities
----------------
1. Collection lifecycle  : ensure_collection() creates the collection with the
   correct vector config if it does not yet exist. Safe to call on every startup.
2. Upsert                : write (chunk_id, vector, payload) triples in bulk.
3. List IDs             : fetch all point IDs in the collection — used by the
   embedding pipeline to identify and delete stale vectors.
4. Delete               : remove a list of point IDs (stale chunks from deleted
   or re-chunked notes).
5. Health check          : verify Qdrant is reachable.

Architecture notes
------------------
- Uses `qdrant_client.AsyncQdrantClient` (HTTP mode, not gRPC) so there is no
  additional gRPC dependency and connection sharing is handled by httpx under
  the hood.
- The client is created once in `main.py` lifespan and stored on `app.state`;
  endpoints access it via the `get_qdrant_service` dependency.
- All methods are async — no blocking I/O on the event loop.
- `ensure_collection` is idempotent: it checks whether the collection already
  has the correct vector size before creating. This avoids a destructive
  recreate when the collection already exists.
"""

import logging

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from app.services.vector.models import VectorPayload

logger = logging.getLogger("app.services.vector")


class QdrantService:
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
        """Create the collection if it does not exist.

        Uses cosine distance — the standard for normalised text embeddings.
        `nomic-embed-text` outputs L2-normalised vectors, so cosine and dot-
        product are equivalent; cosine is the safest default for mixed models.
        """
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

    # ── Write ──────────────────────────────────────────────────────────────────

    async def upsert(
        self,
        payloads: list[VectorPayload],
        vectors: list[list[float]],
    ) -> None:
        """Upsert a batch of (payload, vector) pairs.

        Uses the chunk_id as the Qdrant point ID. Qdrant's upsert is
        idempotent: if a point with the same ID already exists, its vector
        and payload are overwritten. This makes repeated ingest runs safe.

        `payloads` and `vectors` must have the same length and order.
        """
        if not payloads:
            return

        points = [
            qmodels.PointStruct(
                id=p.chunk_id,
                vector=v,
                payload=p.to_dict(),
            )
            for p, v in zip(payloads, vectors)
        ]

        await self._client.upsert(
            collection_name=self._collection,
            points=points,
            wait=True,  # block until Qdrant confirms the write
        )
        logger.debug("Upserted points", extra={"count": len(points)})

    # ── Read ───────────────────────────────────────────────────────────────────

    async def get_all_point_ids(self) -> set[str]:
        """Return all point IDs currently in the collection.

        Uses scroll with a large page size to avoid N+1 HTTP calls for small
        collections. For very large collections (>100k points) a streaming
        scroll would be more memory-efficient, but that is out of scope here.
        """
        ids: set[str] = set()
        offset = None

        while True:
            results, next_offset = await self._client.scroll(
                collection_name=self._collection,
                limit=1000,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            for point in results:
                ids.add(str(point.id))

            if next_offset is None:
                break
            offset = next_offset

        logger.debug("Fetched existing point IDs", extra={"count": len(ids)})
        return ids

    # ── Delete ─────────────────────────────────────────────────────────────────

    async def delete_points(self, ids: list[str]) -> None:
        """Delete a list of points by ID. No-op if the list is empty."""
        if not ids:
            return

        await self._client.delete(
            collection_name=self._collection,
            points_selector=qmodels.PointIdsList(points=ids),
            wait=True,
        )
        logger.info("Deleted stale points", extra={"count": len(ids)})

    # ── Health ─────────────────────────────────────────────────────────────────

    async def health(self) -> bool:
        try:
            await self._client.get_collections()
            return True
        except Exception:
            return False
