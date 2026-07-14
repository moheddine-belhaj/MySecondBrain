# Architecture Overview

## System Architecture

```
Browser
  │
  └─► Nuxt 3 (port 3000)
          │
          └─► FastAPI (port 8000)
                  │
                  ├─► Qdrant (port 6333)   ← vector storage + search
                  └─► Ollama (port 11434)  ← embeddings + chat generation
```

All services run as Docker containers on a single bridge network (`second-brain-net`).
Service discovery uses Docker DNS: `qdrant:6333`, `ollama:11434`, `backend:8000`.

## Request Flows

### Search (`GET /api/v1/search`)
```
browser → Nuxt → GET /api/v1/search?q=...&mode=hybrid
                      │
                      ├─ [semantic/hybrid] embed query → Qdrant ANN search
                      │
                      ├─ [keyword/hybrid]  BM25 search (in-process, no network)
                      │
                      ├─ weighted RRF fusion
                      │
                      └─ deduplicate → trim → return RetrievedChunk[]
```

### Chat (`POST /api/v1/chat`)
```
browser → POST /api/v1/chat  {session_id, query}
              │
              ├─ retrieve top_k chunks (hybrid search above)
              ├─ build prompt (system + history + context chunks + query)
              ├─ call Ollama /api/chat (streaming SSE)
              └─ return ChatResponse  {answer, sources, session_id}
```

### Ingest (`POST /api/v1/ingest`)
```
POST /api/v1/ingest
    │
    ├─ VaultScanner   → scan .md files → ScanResult
    ├─ MarkdownChunker → split by headings → Chunk[]
    ├─ OllamaService  → embed_batch() → vectors[]
    ├─ QdrantService  → upsert() + delete_stale()
    └─ KeywordIndex   → invalidate() (rebuilt on next search)
```

### Incremental Sync (`POST /api/v1/ingest/sync`)
```
POST /api/v1/ingest/sync
    │
    ├─ VaultScanner      → scan current hashes
    ├─ IndexStateStore   → load persisted hashes from data/index_state.json
    ├─ diff              → new / modified / deleted / unchanged
    ├─ process only changed notes (embed + upsert / delete)
    ├─ IndexStateStore   → save updated hashes
    └─ KeywordIndex      → invalidate() if any changes
```

## Module Map

```
backend/app/
├── api/
│   ├── system.py              /health, /readiness, /status, /models
│   └── v1/endpoints/
│       ├── chat.py            POST /api/v1/chat
│       ├── search.py          GET  /api/v1/search
│       └── ingest.py          POST /api/v1/ingest, /ingest/sync, /ingest/scan
│
├── config/
│   └── settings.py            All config from env via pydantic-settings
│
├── services/
│   ├── vault/
│   │   ├── scanner.py         Recursively find .md files, parse frontmatter
│   │   └── parser.py          Extract title, tags, headings, wikilinks, hash
│   │
│   ├── ingestion/
│   │   ├── chunker.py         Split notes by heading hierarchy
│   │   └── embedder.py        Batch embed via Ollama
│   │
│   ├── retrieval/
│   │   ├── engine.py          7-stage pipeline: embed→search→BM25→fuse→dedup→trim→enrich
│   │   ├── keyword_index.py   In-process BM25 index (rank_bm25)
│   │   ├── ranker.py          sort_by_score(), rrf_fuse(), weighted_rrf_fuse()
│   │   ├── deduplicator.py    Heading-level + per-note dedup
│   │   └── models.py          RetrievalQuery, RetrievalResult, RetrievedChunk
│   │
│   ├── vector/
│   │   ├── client.py          QdrantService: search, upsert, delete, scroll
│   │   └── repository.py      VectorRepository (abstract base)
│   │
│   ├── llm/
│   │   ├── ollama.py          OllamaService: embed(), chat(), stream_chat()
│   │   └── base.py            EmbeddingProvider, LLMProvider (abstract)
│   │
│   ├── synthesis/
│   │   ├── synthesizer.py     LlamaIndex-based response synthesis
│   │   ├── context_builder.py Assemble context from RetrievedChunk[]
│   │   └── prompt_config.py   Prompt templates
│   │
│   ├── indexing/
│   │   ├── state_store.py     Atomic JSON read/write for note hash state
│   │   └── sync_engine.py     IncrementalSyncEngine: diff + selective re-index
│   │
│   ├── security/
│   │   ├── guard.py           SecurityGuard: sanitize + detect injections
│   │   ├── rate_limiter.py    Token-bucket rate limiter
│   │   ├── input_sanitizer.py Strip dangerous patterns from user input
│   │   ├── output_sanitizer.py Strip PII/secrets from LLM output
│   │   ├── injection_detector.py Prompt injection pattern matching
│   │   └── audit_logger.py    Security event logging
│   │
│   └── session/
│       └── store.py           In-memory session store (TTL, max sessions)
│
├── startup.py                 Pre-flight validation (vault, Qdrant, Ollama)
├── main.py                    FastAPI app factory + lifespan
├── middleware.py              RequestID + structured request logging
├── exceptions.py              AppError hierarchy + exception handlers
└── logging_config.py          JSONFormatter + ConsoleFormatter
```

## Key Design Decisions

**Why LlamaIndex for synthesis?**
LlamaIndex's `get_response_synthesizer()` handles context packing and multi-chunk answer synthesis out of the box. The core retrieval pipeline is our own code — LlamaIndex is only used for the final synthesis step.

**Why Qdrant?**
Proper server with REST + gRPC, payload filtering, named vectors, and a snapshot API for backups. Chroma is dev-only; FAISS has no server mode.

**Why Ollama?**
Single-binary local model runtime. No GPU required for small models. Pull models like Docker images. HTTP API compatible with OpenAI clients.

**Why BM25 over Qdrant sparse vectors (SPLADE)?**
For a personal vault (<50k chunks), in-process BM25 is adequate. No extra index, no SPLADE model download, easier to test without running Qdrant. The engine interface (`RetrievalQuery.mode`) is unchanged if you swap to sparse vectors later.

**Why Reciprocal Rank Fusion (RRF) over linear score combination?**
Cosine scores (0–1) and BM25 scores (0–∞) are on different scales. RRF uses only ranks, so scale incompatibility is irrelevant. Robust, no normalization step needed.

**Why pydantic-settings for config?**
Every setting is typed and validated at startup. `is_production` property enables environment-specific behaviour. No `os.getenv()` scattered through business logic.

**Why a separate `/readiness` probe?**
Docker HEALTHCHECK uses `/health` (liveness — is the process alive?). Load balancers and Kubernetes use `/readiness` (are dependencies up?). Separating them prevents a restart loop when Qdrant is temporarily unreachable: the container stays alive (liveness = ok) but is removed from rotation (readiness = fail).
