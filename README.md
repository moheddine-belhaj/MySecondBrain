# MySecondBrain

Local-first AI Second Brain — powered by FastAPI, LlamaIndex, Qdrant, Ollama, and Nuxt 3.

## Architecture

```
Browser → Nuxt 3 → FastAPI → LlamaIndex ─┬─ Qdrant  (vector store)
                                           └─ Ollama  (embed + generate)
                                                ▲
                                        Obsidian Vault (markdown)
```

See [docs/architecture.md](docs/architecture.md) for full rationale.

## Monorepo Structure

```
second-brain/
├── backend/                 # Python · FastAPI · LlamaIndex
│   ├── app/
│   │   ├── api/v1/endpoints/  # chat · ingest · search
│   │   ├── rag/               # RAG orchestration
│   │   ├── ingestion/         # vault reader + chunker
│   │   ├── retrieval/         # Qdrant search
│   │   ├── prompts/           # prompt templates
│   │   ├── security/          # validation, rate-limiting
│   │   ├── services/          # cross-cutting services
│   │   ├── config/            # pydantic-settings
│   │   └── models/            # request/response schemas
│   ├── tests/
│   ├── requirements/
│   └── pyproject.toml
│
├── frontend/                # Vue 3 · Nuxt 3 · TailwindCSS
│   ├── components/
│   ├── composables/
│   ├── pages/
│   ├── stores/
│   ├── services/
│   ├── types/
│   └── assets/
│
├── vault/                   # Obsidian markdown notes (git-ignored)
├── docker/                  # Compose + Dockerfiles
├── scripts/                 # Helper scripts
└── docs/                    # Architecture docs
```

## Quick Start

```bash
# 1. Start infrastructure
cd docker && docker compose up qdrant ollama -d

# 2. Pull required models
./scripts/pull_models.sh

# 3. Start backend
cd backend && cp .env.example .env
pip install -r requirements/dev.txt
uvicorn app.main:app --reload

# 4. Start frontend
cd frontend && npm install && npm run dev
```

### dev

#### BE

```bash
source .venv/bin/activate
```

```bash 
uvicorn app.main:app --reload --port 8000
```


## Stack

| Layer | Technology |
|---|---|
| Frontend | Vue 3 · Nuxt 3 · TailwindCSS · Pinia |
| Backend | Python 3.12 · FastAPI · Pydantic v2 |
| AI | LlamaIndex · Ollama (llama3.2 + nomic-embed-text) |
| Vector DB | Qdrant |
| Infrastructure | Docker Compose |


# Questions: ?

- Run the model in the VPS
- Use open sources API
- k8s cours