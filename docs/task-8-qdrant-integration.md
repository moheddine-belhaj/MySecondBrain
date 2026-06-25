# Task 8 — Qdrant Integration

## Overview

This task wired Qdrant into the application as the vector store backing the embedding pipeline. The goal was to build a clean, provider-neutral abstraction over Qdrant so the rest of the codebase never imports Qdrant types directly — only the concrete `QdrantService` class does.

At the end of this task:
- The vector service layer supports full CRUD + similarity search with metadata filtering.
- Collections and payload indexes are created automatically on startup.
- The embedding pipeline (`EmbeddingPipeline`) is decoupled from Qdrant via the `VectorRepository` interface.
- 187/187 tests pass.

---

## Project Context

This application is a local-first AI "Second Brain" built on:

| Layer | Technology |
|---|---|
| API | FastAPI |
| Vector store | Qdrant (self-hosted via Docker) |
| Embedding model | Ollama (local LLM server) |
| Vault | Obsidian markdown files |

### Pipeline flow (end to end)

```
Obsidian vault (markdown files)
        │
        ▼
  VaultScanner          — discovers and reads .md files
        │
        ▼
  MarkdownChunker       — splits notes into TextChunk objects
        │
        ▼
  EmbeddingPipeline     — orchestrates the full run
        │
   ┌────┴────────────────────┐
   ▼                         ▼
OllamaService          QdrantService
(embed_batch)          (upsert / delete)
```

Search flow (added in Task 8, retrieval orchestration deferred to Task 9):

```
query text → OllamaService.embed() → QdrantService.search() → SearchResult[]
```

---

## What Changed in Task 8

### New: `app/services/vector/repository.py`

Defines `VectorRepository`, an abstract base class (ABC) with 11 abstract methods. Every caller in the app depends on this interface, not on `QdrantService` directly.

```
ensure_collection()         — idempotent collection + index creation
delete_collection()         — drop the collection
upsert(payloads, vectors)   — insert or overwrite points
update_payload(id, updates) — patch metadata without re-embedding
search(vector, ...)         — ANN search with optional filters + score threshold
get_all_point_ids()         — full scroll for stale-chunk detection
count()                     — exact point count
get_collection_info()       — collection config and status
delete_points(ids)          — delete by chunk ID list
delete_by_note_id(note_id)  — filter-based bulk delete for a note
health()                    — liveness probe
```

**Why an ABC?** Swapping to pgvector or Pinecone later only requires a new concrete class — nothing in the endpoint or pipeline layer needs to change.

---

### New: `app/services/vector/filters.py`

`FilterBuilder.build(SearchFilter | None) → qdrant_client.Filter | None`

Translates the pure-Python `SearchFilter` dataclass into Qdrant's native filter model. All `qdrant_client` imports in the filter logic are isolated here — `models.py` and `repository.py` remain provider-neutral.

Supported filters (combined with AND / `must`):

| Field | Qdrant match type | Use case |
|---|---|---|
| `tags` | `MatchAny(any=[...])` | "has any of these tags" |
| `note_id` | `MatchValue(value=...)` | exact note hash |
| `note_path` | `MatchValue(value=...)` | exact file path |
| `note_title` | `MatchValue(value=...)` | exact title |

---

### Updated: `app/services/vector/models.py`

Added `chunk_text: str` to `VectorPayload` and updated `to_dict()` to include it.

**Why store chunk_text in Qdrant?** Search results become self-contained — the caller gets the text back from Qdrant directly without a round-trip to the vault file. This is critical for RAG responses.

Added three new dataclasses:

```python
@dataclass
class SearchFilter:
    tags: list[str] | None = None
    note_id: str | None = None
    note_path: str | None = None
    note_title: str | None = None

@dataclass
class SearchResult:
    chunk_id: str
    score: float
    chunk_text: str
    payload: dict = field(default_factory=dict)

@dataclass
class CollectionInfo:
    name: str
    vector_count: int
    vector_size: int
    distance: str
    status: str
```

---

### Rewritten: `app/services/vector/client.py`

`QdrantService` now fully implements `VectorRepository`. Key implementation details:

**Payload indexes** — created once, right after collection creation. Qdrant uses these to pre-filter candidate points before the ANN scan, so metadata filters are cheap even at scale.

```python
_KEYWORD_INDEXES = ("tags", "note_id", "note_path", "note_title")
_INTEGER_INDEXES = ("chunk_index",)
```

**`upsert`** — uses `wait=True` so callers get a reliable success signal before stats are reported.

**`search`** — passes `score_threshold=None` to Qdrant when the caller passes `0.0` (meaning "no threshold"). Qdrant treats `None` and `0.0` differently.

**`update_payload`** — calls `client.set_payload()` to patch only the provided keys. Other fields are preserved. Used for metadata corrections (re-tagging, path renames) that don't require re-embedding.

**`delete_by_note_id`** — uses `FilterSelector` (filter-based bulk delete) instead of scroll-then-delete. Avoids an extra round-trip when only `note_id` is known.

**`get_all_point_ids`** — scrolls the full collection in pages of 1 000 to collect IDs for stale-chunk detection.

---

### Updated: `app/services/vector/__init__.py`

Exported all new public symbols:

```python
__all__ = [
    "CollectionInfo",
    "FilterBuilder",
    "QdrantService",
    "SearchFilter",
    "SearchResult",
    "VectorPayload",
    "VectorRepository",
]
```

---

### Updated: `app/services/ingestion/embedder.py`

Two changes:

1. **Type hint**: `qdrant: VectorRepository` (was `QdrantService`). The pipeline now depends only on the interface, not the concrete class.

2. **`_build_payload`**: Added `chunk_text=chunk.text` — the decorated chunk text (breadcrumb header + content) is now stored in the Qdrant payload.

---

### Updated: `tests/services/vector/test_payload.py`

- Added `chunk_text` to `_payload()` helper defaults.
- Updated `test_to_dict_contains_all_fields` to include `"chunk_text"` in the expected key set.
- Added `test_chunk_text_stored_verbatim`.

---

### New: `tests/services/vector/test_repository.py`

55 mock-based unit tests. No live Qdrant required — all Qdrant client calls are replaced with `AsyncMock` / `MagicMock`.

Test classes and coverage:

| Class | Tests | What's covered |
|---|---|---|
| `TestFilterBuilder` | 9 | None filter, single fields, combined filters |
| `TestEnsureCollection` | 7 | New collection, existing collection (no-op), index creation calls |
| `TestUpsert` | 5 | Normal upsert, empty list no-op, point structure |
| `TestSearch` | 10 | No filter, with filter, score threshold, empty results, payload mapping |
| `TestDeletePoints` | 3 | Normal delete, empty list no-op |
| `TestDeleteByNoteId` | 3 | Filter selector construction |
| `TestUpdatePayload` | 3 | Partial patch, key forwarding |
| `TestCount` | 3 | Return value mapping |
| `TestGetCollectionInfo` | 7 | Vector config extraction, status value |
| `TestDeleteCollection` | 1 | Delegation to client |
| `TestHealth` | 2 | True on success, False on exception |

---

## Architecture Decisions

**Repository pattern** — `VectorRepository` ABC decouples callers from Qdrant. Concrete class can be swapped without touching the API layer or pipeline.

**Qdrant import isolation** — Only `filters.py` and `client.py` import from `qdrant_client`. Domain types (`models.py`, `repository.py`) are pure Python. This keeps the domain portable and makes unit testing straightforward.

**Payload indexes** — Created once after collection creation. Without them Qdrant falls back to a full payload scan on every filtered query. With them, the filter is applied as a pre-filter before the ANN scan.

**`chunk_text` in payload** — Storing the text alongside the vector makes `SearchResult` self-contained. The RAG layer (Task 9) can return context to the LLM without touching the vault.

**`wait=True` on writes** — All upsert and delete calls block until Qdrant confirms durability. This gives the pipeline a reliable success signal before incrementing stats counters.

---

## Test Results

```
187 passed in X.XXs
```

All tests pass with no live external services required.
