# Task 1 — Initialize Monorepo Structure

## Goal

Create the foundational skeleton of the Second Brain project: directory layout,
Python package declarations, configuration, frontend scaffold, Docker stubs, and
a dev helper script. No business logic is implemented here — the purpose of this
task is to establish conventions that every future task builds on.

---

## Directory Tree Created

```
second-brain/
│
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                        ← FastAPI application factory
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── v1/
│   │   │       ├── __init__.py            ← Router aggregator
│   │   │       └── endpoints/
│   │   │           ├── __init__.py
│   │   │           ├── chat.py            ← stub
│   │   │           ├── ingest.py          ← stub
│   │   │           └── search.py          ← stub
│   │   ├── config/
│   │   │   ├── __init__.py
│   │   │   └── settings.py               ← pydantic-settings singleton
│   │   ├── models/          __init__.py
│   │   ├── rag/             __init__.py
│   │   ├── ingestion/       __init__.py
│   │   ├── retrieval/       __init__.py
│   │   ├── prompts/         __init__.py
│   │   ├── security/        __init__.py
│   │   └── services/        __init__.py
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── unit/            __init__.py
│   │   └── integration/     __init__.py
│   ├── requirements/
│   │   ├── base.txt                       ← production deps
│   │   └── dev.txt                        ← base + test/lint tools
│   ├── pyproject.toml                     ← ruff, mypy, pytest config
│   └── .env.example                       ← all env vars with safe defaults
│
├── frontend/
│   ├── assets/css/main.css               ← Tailwind entry point
│   ├── components/chat/                  ← placeholder
│   ├── components/ui/                    ← placeholder
│   ├── composables/                      ← placeholder
│   ├── pages/                            ← placeholder
│   ├── stores/                           ← placeholder
│   ├── services/
│   │   └── api.ts                        ← typed $fetch wrappers
│   ├── types/
│   │   └── index.ts                      ← shared TypeScript types
│   ├── nuxt.config.ts                    ← Nuxt 3 configuration
│   └── package.json
│
├── vault/
│   ├── .obsidian/                        ← Obsidian settings (git-ignored)
│   └── README.md                         ← instructions for placing notes
│
├── docker/
│   ├── docker-compose.yml               ← initial stub (replaced in Task 2)
│   ├── Dockerfile.backend               ← initial stub (replaced in Task 2)
│   ├── Dockerfile.frontend              ← initial stub (replaced in Task 2)
│   └── .dockerignore
│
├── scripts/
│   └── pull_models.sh                   ← Ollama model pull helper
│
├── docs/
│   └── architecture.md                  ← module responsibility table + decisions
│
├── .gitignore
└── README.md
```

---

## Files Explained

### `backend/app/main.py`

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import router as api_v1_router
from app.config.settings import settings

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    ...
)

app.include_router(api_v1_router, prefix="/api/v1")

@app.get("/health")
async def health_check() -> dict:
    return {"status": "ok", "version": settings.app_version}
```

**Decisions:**
- `docs_url` is gated behind `settings.debug` — Swagger UI is never exposed in
  production without an explicit environment variable.
- CORS origins come from settings, not hardcoded — safe to deploy behind a
  reverse proxy with a different domain.
- The `/health` endpoint is at the root (`/health`), not under `/api/v1` — load
  balancers and Docker healthchecks should not need to know the API version.

---

### `backend/app/config/settings.py`

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = "Second Brain API"
    app_version: str = "0.1.0"
    debug: bool = False

    allowed_origins: list[str] = ["http://localhost:3000"]

    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "second_brain"

    ollama_base_url: str = "http://localhost:11434"
    ollama_embed_model: str = "nomic-embed-text"
    ollama_chat_model: str = "llama3.2"

    vault_path: str = "./vault"
    chunk_size: int = 512
    chunk_overlap: int = 64

settings = Settings()
```

**Decisions:**
- Every config value has a typed default — the app starts without a `.env`
  file in development. No `os.getenv()` calls exist anywhere else in the
  codebase. All configuration is gathered in one place.
- `case_sensitive=False` — `QDRANT_HOST` and `qdrant_host` both match.
- `settings` is a module-level singleton instantiated at import time. If a
  required env var is missing or malformed, the process exits immediately with a
  clear Pydantic validation error rather than failing silently at runtime.

---

### `backend/app/api/v1/__init__.py` — Router aggregator

```python
from fastapi import APIRouter
from app.api.v1.endpoints import chat, ingest, search

router = APIRouter()
router.include_router(chat.router,   prefix="/chat",   tags=["chat"])
router.include_router(ingest.router, prefix="/ingest", tags=["ingest"])
router.include_router(search.router, prefix="/search", tags=["search"])
```

**Why versioned at `v1`?**
The portfolio website will consume the same API as the frontend. Versioning
allows both consumers to upgrade independently. Breaking changes land in `v2`
without touching `v1` clients.

---

### `backend/requirements/`

| File | Purpose |
|---|---|
| `base.txt` | Production deps: FastAPI, uvicorn, pydantic, LlamaIndex, Qdrant client, Ollama client |
| `dev.txt` | `-r base.txt` + pytest, httpx, ruff, mypy |

Split so the production Docker image does not carry test and lint tooling.

---

### `backend/pyproject.toml`

```toml
[tool.ruff]
line-length = 100
target-version = "py312"
select = ["E", "F", "I", "UP"]   # errors, pyflakes, isort, upgrade suggestions

[tool.mypy]
python_version = "3.12"
strict = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

All tooling configured here so `ruff check .`, `mypy .`, and `pytest` work from
the `backend/` directory with no extra flags.

---

### `frontend/types/index.ts`

```typescript
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: NoteSource[];
  createdAt: string;
}

export interface NoteSource {
  noteTitle: string;
  notePath: string;
  excerpt: string;
  score: number;
}

export interface IngestStatus {
  status: "pending" | "running" | "completed" | "failed";
  totalNotes: number;
  processedNotes: number;
  message?: string;
}
```

Types are defined here at Task 1 so every future component imports from a single
source of truth. They intentionally mirror the backend Pydantic models.

---

### `frontend/services/api.ts`

Thin `$fetch` wrappers over the three API groups. Real implementations are added
per task; the shape of the service layer is established early so components
written in later tasks can import without refactoring.

---

### `frontend/nuxt.config.ts`

```typescript
export default defineNuxtConfig({
  modules: ["@nuxtjs/tailwindcss", "@pinia/nuxt", "@vueuse/nuxt"],
  runtimeConfig: {
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE ?? "http://localhost:8000/api/v1",
    },
  },
  typescript: { strict: true },
  compatibilityDate: "2025-01-01",
});
```

`apiBase` is injected via `runtimeConfig.public` so the same build can target
different backends by setting `NUXT_PUBLIC_API_BASE` — no rebuild needed.

---

### `scripts/pull_models.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
MODELS=("nomic-embed-text" "llama3.2")
for model in "${MODELS[@]}"; do
  ollama pull "$model"
done
```

Pulls both required Ollama models in one command. The `set -euo pipefail` flag
causes the script to fail fast if any pull fails, rather than silently
continuing.

---

### `.gitignore` highlights

| Pattern | Reason |
|---|---|
| `.env` / `.env.*` | Never commit secrets |
| `vault/*.md` | Personal notes are local-only |
| `vault/.obsidian/` | Obsidian workspace config |
| `.venv/` | Virtual environment |
| `node_modules/` `.nuxt/` `.output/` | Build artifacts |

---

## What This Task Enables

- The backend can be imported (`from app.main import app`) without errors.
- All route paths exist (`/health`, `/api/v1/chat`, `/api/v1/ingest`,
  `/api/v1/search`) — they return stubs until Tasks 3/4.
- Tooling (`ruff`, `mypy`, `pytest`) runs with no configuration.
- The frontend scaffold is ready for component development.
- Docker files exist as stubs ready to be replaced in Task 2.

## What Is NOT Done Here

- No AI logic (LlamaIndex, Qdrant, Ollama) — that is Tasks 3 and 4.
- No working Docker setup — replaced in Task 2.
- No real endpoint responses — added in Task 3.
- No frontend pages or components — added in later tasks.
