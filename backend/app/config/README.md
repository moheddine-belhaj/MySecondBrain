# config

`settings.py` defines `Settings` (pydantic-settings). Values come from environment variables or `backend/.env`; the global instance is `settings`.

| Group | Settings (default) |
|-------|--------------------|
| App | `APP_NAME`, `APP_VERSION`, `ENVIRONMENT` (development), `DEBUG` (false), `API_PREFIX` (/api/v1) |
| Logging | `LOG_LEVEL` (INFO), `LOG_FORMAT` (json or console) |
| CORS | `ALLOWED_ORIGINS` (`["http://localhost:3000"]`) |
| Qdrant | `QDRANT_HOST`, `QDRANT_PORT` (6333), `QDRANT_COLLECTION` (second_brain), `QDRANT_VECTOR_SIZE` (768) |
| Ollama | `OLLAMA_BASE_URL`, `OLLAMA_CHAT_MODEL` (qwen2.5), `OLLAMA_EMBED_MODEL` (nomic-embed-text), connect/chat/embed timeouts, `OLLAMA_MAX_RETRIES` (3), `OLLAMA_RETRY_DELAY` |
| Retrieval | `RETRIEVAL_TOP_K` (10), `RETRIEVAL_SCORE_THRESHOLD`, `RETRIEVAL_MAX_CHUNKS_PER_NOTE` (2), `RETRIEVAL_OVER_FETCH_FACTOR` (3) |
| Hybrid search | `HYBRID_DEFAULT_MODE` (hybrid), `HYBRID_SEMANTIC_WEIGHT` (0.7), `HYBRID_KEYWORD_WEIGHT` (0.3), `HYBRID_RRF_K` (60) |
| Synthesis | `SYNTHESIS_MODE` (compact, refine or tree_summarize) |
| Vault / ingestion | `VAULT_PATH`, `CHUNK_SIZE` (512), `CHUNK_OVERLAP` (64), `EMBED_BATCH_SIZE` (32) |
| Incremental sync | `INDEX_STATE_PATH`, `SYNC_INTERVAL_MINUTES` (0 = disabled) |

Computed helpers: `qdrant_url`, `is_production`.

See `../.env.example` for a ready-to-copy template.
