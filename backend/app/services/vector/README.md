# services/vector

Vector storage on Qdrant.

- `repository.py`: `VectorRepository`, the abstract contract (ensure/delete collection, upsert, search, delete, scroll, count, health).
- `client.py`: `QdrantService`, the Qdrant implementation. It creates the collection and payload indexes on first use.
- `filters.py`: `FilterBuilder` turns a `SearchFilter` (tags, note path, ...) into a Qdrant filter.
- `models.py`: `VectorPayload` (metadata stored with each point), `SearchFilter`, `SearchResult`, `CollectionInfo`.
