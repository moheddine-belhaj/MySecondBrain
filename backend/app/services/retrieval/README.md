# services/retrieval

`RetrievalEngine.retrieve()` finds the chunks relevant to a query.

## Modes
- `semantic`: embed the query, vector search, sort by cosine score
- `keyword`: BM25 only
- `hybrid` (default): both, fused with weighted Reciprocal Rank Fusion

## Pipeline
embed → over-fetch from Qdrant (`top_k × over_fetch_factor`) → BM25 → fuse (RRF) → deduplicate → trim to `top_k` → number results.

## Files
- `engine.py`: the orchestrator.
- `keyword_index.py`: in-memory BM25 `KeywordIndex`. It builds lazily from Qdrant and rebuilds after `invalidate()` (called by ingest/sync).
- `ranker.py`: `sort_by_score`, `rrf_fuse`, `weighted_rrf_fuse`.
- `deduplicator.py`: removes near-duplicate chunks and caps chunks per note.
- `models.py`: `RetrievalQuery`, `RetrievedChunk`, `RetrievalResult` (includes timing metadata).
