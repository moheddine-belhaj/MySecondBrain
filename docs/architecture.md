# Architecture Overview

## Request Flow

```
Browser → Nuxt 3 (SSR/SPA) → FastAPI → LlamaIndex
                                           ├── Qdrant  (vector retrieval)
                                           └── Ollama  (embedding + generation)
```

## Module Responsibilities

| Module | Responsibility |
|---|---|
| `app/ingestion` | Read vault markdown, chunk, embed, upsert into Qdrant |
| `app/retrieval` | Semantic search against Qdrant, rerank, return chunks |
| `app/rag` | Orchestrate retrieval + prompt assembly + LLM call |
| `app/prompts` | Prompt templates (system, RAG, chat history) |
| `app/api/v1` | HTTP boundary — thin routers, no business logic |
| `app/services` | Cross-cutting services (e.g. session store) |
| `app/security` | Input validation, rate limiting, CORS config |
| `app/config` | Pydantic-settings — all config from env |
| `app/models` | Pydantic request/response schemas |

## Key Design Decisions

**Why LlamaIndex over LangChain?**
LlamaIndex has a tighter scope (data + retrieval) which maps directly to what we need. LangChain adds abstractions that invite overengineering.

**Why Qdrant over Chroma/FAISS?**
Qdrant ships as a proper server (Docker), has filtering, and scales. Chroma is dev-only; FAISS has no server mode.

**Why Ollama?**
All-in-one local model runtime. Pulls models like Docker images. No GPU required for small models.

**Why versioned API (`/api/v1`)?**
The frontend and the portfolio website will both hit this API. Versioning keeps future changes non-breaking.

**Why `pydantic-settings`?**
Every config value is typed and validated at startup. No `os.getenv()` scattered through business logic.
