# Backend

FastAPI service for the local-first "Second Brain": it indexes an Obsidian vault into Qdrant and answers questions over it with Ollama.

## Stack
- **FastAPI**: HTTP API (Python 3.12)
- **Qdrant**: vector store
- **Ollama**: chat model (default `qwen2.5`) and embeddings (`nomic-embed-text`)
- **LlamaIndex**: response synthesis
- **rank_bm25**: keyword search

## Layout
| Path | Purpose |
|------|---------|
| [app/](app/README.md) | Application code |
| [tests/](tests/README.md) | Pytest suite |
| [requirements/](requirements/README.md) | Dependency files |
| `vault/` | Sample Obsidian vault (`VAULT_PATH` default) |
| `.env.example` | All configurable settings |
| `pyproject.toml` | Project metadata, ruff, mypy, pytest config |

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements/dev.txt
cp .env.example .env
uvicorn app.main:app --reload
```
Docs UI: http://localhost:8000/docs (needs Qdrant on 6333 and Ollama on 11434; see `../docker`).

## Test
```bash
pytest
```

## Request flow (RAG chat)
`request → security guard (sanitize + injection check) → retrieval (embed → vector + BM25 → fuse → dedupe) → chunk scan → synthesis (LLM) → output sanitize → response`
