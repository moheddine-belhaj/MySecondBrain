# api/v1

`__init__.py` assembles the router; endpoints live in `endpoints/`. All paths are prefixed with `/api/v1`.

| Router | Prefix | File |
|--------|--------|------|
| chat | `/chat` | `endpoints/chat.py` |
| ingest | `/ingest` | `endpoints/ingest.py` |
| search | `/search` | `endpoints/search.py` |

## Chat (`/chat`)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/chat` | Plain chat, blocking, with session memory |
| POST | `/chat/stream` | Plain chat, streamed over SSE |
| POST | `/chat/rag` | RAG chat grounded in vault notes, blocking, returns sources |
| POST | `/chat/rag/stream` | RAG chat streamed over SSE |
| GET | `/chat/sessions/{session_id}` | Conversation history |
| DELETE | `/chat/sessions/{session_id}` | Delete a session |

Chat requests carry `messages` and an optional `session_id`. RAG requests also take `top_k` (1-20), `score_threshold`, `tags`, `note_path` and `deduplicate`. Rate limit: 30 req/min, burst 10.

## Search (`GET /search`)
Query params: `q` (required, max 500 chars), `top_k` (1-50), `score_threshold`, `tags` (OR match), `note_path`, `deduplicate`, `mode` (`semantic`, `keyword` or `hybrid`), `semantic_weight`, `keyword_weight`. Weights and mode default to server settings.

## Ingest (`/ingest`)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/ingest/scan` | Scan the vault and preview parsed notes (no indexing) |
| POST | `/ingest/preview` | Preview how notes are chunked |
| POST | `/ingest` | Full pipeline: scan, chunk, embed, index |
| GET | `/ingest/status` | Status of the last ingestion |
| POST | `/ingest/sync` | Incremental sync of changed notes only |
| GET | `/ingest/sync/status` | Result of the last sync |

Rate limit: 5 req/min, burst 2. Ingest and sync mark the BM25 keyword index stale so it rebuilds on the next search.

Streaming endpoints emit Server-Sent Events (`StreamEvent` objects, see `models/chat.py`).
