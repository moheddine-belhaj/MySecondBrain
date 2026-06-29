# Task 9 — Retrieval Engine

## Overview

This task built the retrieval engine — the layer that sits between the user's raw search query and the Qdrant vector store. It converts a query string into a ranked, deduplicated list of relevant chunks, ready to be passed to an LLM as context.

At the end of this task:
- `GET /api/v1/search?q=...` is fully functional: embeds the query, searches Qdrant, deduplicates, ranks, and returns structured results.
- The engine is provider-neutral (depends on `EmbeddingProvider` + `VectorRepository` ABCs).
- Structured for future hybrid search (RRF scaffold in place).
- 232/232 tests pass.

---

## Project Context

This is a local-first AI "Second Brain" — RAG over an Obsidian vault. Task 9 completes the read path:

```
User query (text)
      │
      ▼
 EmbeddingProvider.embed()     — Ollama: text → vector
      │
      ▼
 VectorRepository.search()     — Qdrant: vector → top candidates
      │
      ▼
 Ranker.sort_by_score()        — re-sort (makes hybrid fusion easy later)
      │
      ▼
 Deduplicator.deduplicate()    — remove heading/note duplicates
      │
      ▼
 Trim to top_k + assign ranks  — 1-based rank numbers
      │
      ▼
 RetrievalResult               — structured response with observability fields
```

---

## What Changed in Task 9

### New: `app/services/retrieval/models.py`

Three pure-Python dataclasses — no Qdrant, no FastAPI imports.

**`RetrievalQuery`** — caller config for one retrieval run:

| Field | Default | Purpose |
|---|---|---|
| `text` | — | Raw user query string |
| `top_k` | 10 | Final result count |
| `score_threshold` | 0.0 | Min cosine score (0 = no filter) |
| `filters` | None | Optional `SearchFilter` for tag/path/note filtering |
| `deduplicate` | True | Toggle deduplication |
| `max_chunks_per_note` | 2 | Diversity cap: max chunks per note_id |
| `over_fetch_factor` | 3 | Qdrant fetch = top_k × factor (headroom for dedup) |

**`RetrievedChunk`** — one ranked result, self-contained (all note metadata included so callers don't need a vault lookup).

**`RetrievalResult`** — full response with observability metadata: `total_candidates`, `deduplicated_count`, `latency_ms`, `filters_applied`.

---

### New: `app/services/retrieval/deduplicator.py`

`Deduplicator` applies two strategies in order, operating on an already-score-sorted list:

**1. Heading dedup**
Chunks sharing `(note_id, heading_path)` are adjacent pieces of the same section. Keeping all of them inflates context with near-identical text. The first (highest-scoring) chunk per heading key is kept; the rest are dropped.

**2. Per-note cap** (`max_per_note`, default 2)
After heading dedup, limit how many chunks from a single `note_id` appear in the final result. Prevents one very relevant note from flooding the top-k and squeezing out other relevant sources.

Returns `(kept_list, removed_count)` so the engine can report `deduplicated_count` in the response.

---

### New: `app/services/retrieval/ranker.py`

`Ranker` provides two static methods:

**`sort_by_score(results)`** — sort by cosine similarity descending. Qdrant already returns sorted results, but explicit re-sorting makes the pipeline correct when hybrid fusion (which mixes multiple ranked lists) is added.

**`rrf_fuse(*ranked_lists)`** — Reciprocal Rank Fusion across multiple ranked lists. Implements the standard RRF formula:

```
score(d) = Σ_i  1 / (k + rank_i(d))      k = 60
```

Not used in the current pipeline (pure vector only), but ready to fuse a BM25 keyword ranking with the vector ranking for hybrid search. Candidates absent from a list get a worst-case rank.

---

### New: `app/services/retrieval/engine.py`

`RetrievalEngine` orchestrates the full pipeline. Stateless between calls.

```python
engine = RetrievalEngine(embedding_provider, qdrant, ...)
result = await engine.retrieve(RetrievalQuery(text="what is RAG?", top_k=5))
```

**Logging per stage (all at DEBUG except first/last at INFO):**

| Stage | Log fields |
|---|---|
| Start | query (truncated), top_k, threshold, filters, over_fetch |
| Embed | embed_ms, vector dim |
| Candidates | fetched count, fetch_limit, top/min score |
| Dedup | removed, remaining |
| Complete | results, total_candidates, dedup_removed, latency_ms, top/bottom score |

Private helper `_to_retrieved_chunk()` extracts all payload fields from a `SearchResult` into a `RetrievedChunk` with defaults for missing keys (safe for old index entries).

---

### New: `app/services/retrieval/__init__.py`

Exports: `Deduplicator`, `Ranker`, `RetrievalEngine`, `RetrievalQuery`, `RetrievalResult`, `RetrievedChunk`.

---

### Updated: `app/config/settings.py`

Added four retrieval knobs (all overridable via `.env`):

```
RETRIEVAL_TOP_K=10
RETRIEVAL_SCORE_THRESHOLD=0.0
RETRIEVAL_MAX_CHUNKS_PER_NOTE=2
RETRIEVAL_OVER_FETCH_FACTOR=3
```

---

### Updated: `app/models/search.py`

Replaced the old stub `SearchResult` with two Pydantic response models:

**`RetrievedChunkResponse`** — one result item with `chunk_id`, `score`, `rank`, `chunk_text`, and all note metadata fields.

**`SearchResponse`** — the full endpoint response:
```json
{
  "query": "what is RAG?",
  "results": [...],
  "total_candidates": 30,
  "deduplicated_count": 4,
  "latency_ms": 142.3,
  "filters_applied": false
}
```

---

### Updated: `app/dependencies.py`

Added `get_retrieval_engine` dependency and `RetrievalDep` type alias.

`RetrievalEngine` is constructed per-request from the shared `app.state` providers (no new connections). Changed `get_qdrant_service` return type annotation to `VectorRepository` (the ABC) to align with the repository pattern established in Task 8.

---

### Updated: `app/api/v1/endpoints/search.py`

Replaced the stub with a fully wired endpoint:

```
GET /api/v1/search
  ?q=<query>             required, min_length=1
  &top_k=10              optional, 1–50
  &score_threshold=0.0   optional, 0.0–1.0
  &tags=ai&tags=python   optional, multi-value (OR match)
  &note_path=folder/n.md optional
  &deduplicate=true      optional
```

---

### New: `tests/services/retrieval/`

45 new tests across three files (all mock-based, no live services):

| File | Tests | Coverage |
|---|---|---|
| `test_deduplicator.py` | 11 | heading dedup, per-note cap, combined, edge cases |
| `test_ranker.py` | 10 | score sort, stable on ties, no mutation, RRF fuse |
| `test_engine.py` | 24 | basic flow, over-fetch, filters, dedup on/off, ranking, field mapping |

---

## Architecture Decisions

**Over-fetching** — Deduplication shrinks the candidate pool. Fetching `top_k × over_fetch_factor` from Qdrant before deduplication ensures the final list fills `top_k` even after several chunks are removed. Factor defaults to 3 (configurable).

**Two-stage dedup** — heading dedup first removes adjacent splits of the same section (most common case), then the per-note cap prevents any single note from dominating. Running them separately keeps each stage simple and independently testable.

**RRF scaffold** — `Ranker.rrf_fuse()` is implemented but not wired into the engine yet. Hybrid search requires a BM25 / full-text index alongside Qdrant. The RRF method is covered by tests so it's safe to wire in without regressions.

**Provider neutrality** — `RetrievalEngine` depends on `EmbeddingProvider` and `VectorRepository` ABCs. Swapping Ollama for OpenAI or Qdrant for pgvector requires zero changes to the engine.

**`_to_retrieved_chunk` defaults** — all `payload.get(key, default)` calls use safe defaults. This makes the engine forward-compatible: if a new field is added to the payload schema, old indexed chunks won't cause KeyErrors at retrieval time.

---

## How to Test the Changes

### Prerequisites

Qdrant and Ollama must be running, and the vault must already be indexed (run `POST /api/v1/ingest` first if not done).

```bash
# Start services (if using Docker)
docker compose up -d qdrant

# Start the API
cd backend && .venv/bin/uvicorn app.main:app --reload
```

### 1. Basic search

```bash
curl -s "http://localhost:8000/api/v1/search?q=what+is+machine+learning" | jq .
```

Expected shape:
```json
{
  "query": "what is machine learning",
  "results": [
    {
      "chunk_id": "...",
      "score": 0.87,
      "rank": 1,
      "chunk_text": "[Note: ...]\n\n...",
      "note_title": "...",
      "note_path": "...",
      "tags": [...],
      "heading_path": [...],
      "chunk_index": 0,
      "total_chunks": 3,
      "word_count": 210,
      "note_modified_at": "..."
    }
  ],
  "total_candidates": 30,
  "deduplicated_count": 4,
  "latency_ms": 145.2,
  "filters_applied": false
}
```

### 2. Score threshold

Only return chunks with similarity ≥ 0.75:

```bash
curl -s "http://localhost:8000/api/v1/search?q=neural+networks&score_threshold=0.75" | jq '.results | length'
```

### 3. Tag filter

```bash
curl -s "http://localhost:8000/api/v1/search?q=transformers&tags=ai&tags=deep-learning" | jq '.filters_applied'
# → true
```

### 4. Verify deduplication

Turn off deduplication and compare result count:

```bash
curl -s "http://localhost:8000/api/v1/search?q=python&deduplicate=false&top_k=20" | jq '.results | length'
curl -s "http://localhost:8000/api/v1/search?q=python&deduplicate=true&top_k=20"  | jq '.results | length, .deduplicated_count'
```

With deduplication on you should see `deduplicated_count > 0` if the vault has notes with multiple chunks per heading.

### 5. Path filter

```bash
curl -s "http://localhost:8000/api/v1/search?q=deployment&note_path=devops/docker.md" | jq .
```

### 6. Reduced top_k

```bash
curl -s "http://localhost:8000/api/v1/search?q=RAG&top_k=3" | jq '.results | length'
# → 3 (or fewer if vault has <3 relevant chunks)
```

### 7. Unit tests only (no live services)

```bash
cd backend
.venv/bin/python -m pytest tests/services/retrieval/ -v
# → 45 passed
```

### 8. Full suite

```bash
.venv/bin/python -m pytest
# → 232 passed
```

---

## Test Results

```
232 passed in 1.42s
```

All tests pass with no live external services required for the unit suite.
