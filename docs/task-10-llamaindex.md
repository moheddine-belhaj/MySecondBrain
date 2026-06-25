# Task 10 — LlamaIndex Integration

## Overview

This task integrates LlamaIndex into the architecture — specifically and only where it adds genuine value: **response synthesis**.

LlamaIndex is used for one thing: taking the chunks our `RetrievalEngine` already retrieved and turning them into a coherent, grounded answer. Everything else (vault scanning, chunking, embedding, vector storage, retrieval pipeline) stays in our own code because those layers require Obsidian-specific logic and direct control.

At the end of this task:
- `POST /api/v1/chat/rag` is live: retrieves vault chunks, synthesizes an answer via LlamaIndex, returns sources.
- `POST /api/v1/chat` and `POST /api/v1/chat/stream` are **unchanged** (plain LLM, no retrieval).
- `GET /api/v1/search` is **unchanged** (pure retrieval, no synthesis).
- LlamaIndex is isolated to one file: `app/services/synthesis/synthesizer.py`.
- 248/248 tests pass.

---

## Architecture: Where LlamaIndex Sits

```
POST /api/v1/chat/rag
        │
        ▼
  RetrievalEngine.retrieve()            ← Task 9 (our code, unchanged)
     embed → over-fetch → rank → dedup → trim
        │
        │  list[RetrievedChunk]
        ▼
  ResponseSynthesizer.synthesize()      ← Task 10 (LlamaIndex lives here only)
     convert chunks → LlamaIndex nodes
     get_response_synthesizer() → asynthesize()
     CompactAndRefine: pack context → fill QA prompt → call Ollama → refine if needed
        │
        ▼
  RagChatResponse
     content, sources, retrieval_latency_ms, synthesis_latency_ms,
     total_candidates, deduplicated_count, filters_applied
```

---

## What LlamaIndex Provides Here

### 1. Context compaction (`ResponseMode.COMPACT`)

When `top_k=5` chunks are retrieved, LlamaIndex's `PromptHelper` measures how many fit in the model's context window. If they all fit: one prompt, one LLM call. If they don't: compact the overflow into a second pass (refine mode). We don't write any token-counting or prompt-splitting code.

### 2. Structured prompt management

LlamaIndex's `PromptTemplate` takes a template string with named slots (`{context_str}`, `{query_str}`) and fills them consistently. Our custom prompts (`QA_PROMPT`, `REFINE_PROMPT`) control the exact instructions; LlamaIndex handles the filling and escape logic.

### 3. Multi-pass synthesis (Refine mode)

`ResponseMode.REFINE` generates an initial answer from the first chunk, then iterates over remaining chunks refining the answer. Configurable via `SYNTHESIS_MODE=refine`. Useful when notes are long and a single context window can't hold all retrieved chunks.

---

## What LlamaIndex Does NOT Do In This Project

| Layer | Our code | LlamaIndex skipped? |
|---|---|---|
| Vault scanning | `VaultScanner` | Yes — Obsidian-specific |
| Markdown parsing | `VaultParser` | Yes — heading-aware |
| Chunking | `Chunker` | Yes — heading-aware splits |
| Embedding | `OllamaService.embed_batch()` | Yes — via `EmbeddingProvider` ABC |
| Vector storage | `QdrantService` | Yes — via `VectorRepository` ABC |
| Retrieval pipeline | `RetrievalEngine` | Yes — custom dedup + ranking |
| **Response synthesis** | — | **No — this is where LlamaIndex is used** |

---

## What Changed in Task 10

### New: `app/services/synthesis/models.py`

```python
@dataclass
class SynthesisResult:
    answer: str
    source_chunks: list[RetrievedChunk]
    latency_ms: float
```

Simple output contract. Keeps synthesis return type decoupled from LlamaIndex's `Response` object.

---

### New: `app/services/synthesis/prompts.py`

Two `PromptTemplate` objects for the QA and refine passes:

**`QA_PROMPT`** — tells the LLM to answer only from the provided note excerpts and cite sources. Variable slots: `{context_str}`, `{query_str}`.

**`REFINE_PROMPT`** — instructs the LLM to refine an existing partial answer with additional excerpts, or return it unchanged if nothing new is relevant. Variable slots: `{context_msg}`, `{query_str}`, `{existing_answer}`.

---

### New: `app/services/synthesis/synthesizer.py`

The only file in the codebase that imports LlamaIndex.

**`ResponseSynthesizer`** — wraps `get_response_synthesizer()` from LlamaIndex core:

```python
class ResponseSynthesizer:
    def __init__(self, llm: object, mode: str = "compact") -> None: ...
    async def synthesize(self, query: str, chunks: list[RetrievedChunk]) -> SynthesisResult: ...
```

Internals:
- Calls `_chunk_to_node()` to convert each `RetrievedChunk` to a `NodeWithScore` (LlamaIndex's format).
- Calls `self._synth.asynthesize(query, nodes=nodes)`.
- Returns `SynthesisResult` — no LlamaIndex types leak to callers.
- If `chunks` is empty: returns a fallback message without calling the LLM.
- If `response.response` is `None`: returns the fallback message.

**`_chunk_to_node(chunk)`** — pure conversion function, fully covered by unit tests:

```python
TextNode(text=chunk.chunk_text, metadata={...}, id_=chunk.chunk_id)
NodeWithScore(node=node, score=chunk.score)
```

**No LlamaIndex global `Settings` used** — the LLM is passed explicitly to `get_response_synthesizer(llm=...)`. This avoids module-level state that makes testing and multi-instance setups difficult.

---

### New: `app/services/synthesis/__init__.py`

Exports: `ResponseSynthesizer`, `SynthesisResult`.

---

### Updated: `app/config/settings.py`

```
SYNTHESIS_MODE=compact    # compact | refine | tree_summarize
```

Passed directly to `ResponseMode(mode)` in LlamaIndex.

---

### Updated: `app/models/chat.py`

**`RagChatRequest`** — extends `ChatRequest` with retrieval parameters:

| Field | Default | Purpose |
|---|---|---|
| `messages` | — | Conversation history; last message is the retrieval query |
| `top_k` | 5 | Max chunks to retrieve |
| `score_threshold` | 0.0 | Min similarity score |
| `tags` | None | Filter by tags (OR match) |
| `note_path` | None | Filter by exact note path |
| `deduplicate` | True | Heading/note deduplication |

**`RagChatResponse`** — adds observability fields on top of `content` and `sources`:

```json
{
  "id": "...",
  "role": "assistant",
  "content": "RAG stands for...",
  "sources": [
    {"note_title": "...", "note_path": "...", "excerpt": "...", "score": 0.89}
  ],
  "retrieval_latency_ms": 180.4,
  "synthesis_latency_ms": 1420.1,
  "total_candidates": 15,
  "deduplicated_count": 2,
  "filters_applied": false,
  "created_at": "..."
}
```

---

### Updated: `app/api/v1/endpoints/chat.py`

Added `POST /api/v1/chat/rag`:

```
POST /api/v1/chat/rag
Body: RagChatRequest
  messages[]: role + content
  top_k:            1–20 (default 5)
  score_threshold:  0.0–1.0 (default 0.0)
  tags[]:           optional, multi-value OR filter
  note_path:        optional exact path filter
  deduplicate:      true/false (default true)
```

The existing `POST /chat` and `POST /chat/stream` endpoints are untouched.

---

### Updated: `app/dependencies.py`

Added `get_synthesizer` and `SynthesisDep`:

```python
async def get_synthesizer(request: Request) -> ResponseSynthesizer:
    return ResponseSynthesizer(
        llm=request.app.state.llamaindex_llm,
        mode=_settings.synthesis_mode,
    )

SynthesisDep = Annotated[ResponseSynthesizer, Depends(get_synthesizer)]
```

`ResponseSynthesizer` is stateless between calls — safe and cheap to construct per-request.

---

### Updated: `app/main.py`

Added LlamaIndex Ollama LLM initialization in lifespan:

```python
app.state.llamaindex_llm = LlamaIndexOllama(
    model=settings.ollama_chat_model,
    base_url=settings.ollama_base_url,
    request_timeout=settings.ollama_chat_timeout,
)
```

**Design decision: two Ollama clients.**
`OllamaService` (our httpx-based client) handles embedding and plain chat. `LlamaIndexOllama` (LlamaIndex's internal client) handles synthesis. They share the same URL and model but have separate HTTP clients. This is intentional:

- LlamaIndex's Ollama adapter manages its own connection and timeout logic, which we can't control without forking it.
- Trying to bridge the two would require implementing LlamaIndex's `CustomLLM` ABC (~8 abstract methods) just to avoid a second HTTP client — a poor trade-off.
- Two HTTP clients to the same local server is harmless: Ollama handles concurrent requests on its own goroutine pool.

---

### Updated: `requirements/base.txt`

```
llama-index-core==0.12.6
llama-index-llms-ollama==0.5.0
```

Removed: `llama-index==0.12.0`, `llama-index-vector-stores-qdrant`, `llama-index-embeddings-ollama` — these were placeholders from the initial requirements file. We don't use LlamaIndex's vector store or embedding adapters.

---

### New: `tests/services/synthesis/test_synthesizer.py`

16 tests, all mock-based (no live services):

| Class | Tests | Coverage |
|---|---|---|
| `TestChunkToNode` | 8 | node text, score, id, metadata fields |
| `TestResponseSynthesizer` | 8 | empty chunks fallback, query forwarding, node count, answer extraction, source chunks, latency, None response, mode wiring |

---

## Replacing LlamaIndex Later

If you want to swap LlamaIndex out (e.g., for a custom synthesis or a different framework):

1. Edit `app/services/synthesis/synthesizer.py` only.
2. The contract: `synthesize(query: str, chunks: list[RetrievedChunk]) → SynthesisResult`.
3. Remove `llama-index-core` and `llama-index-llms-ollama` from `requirements/base.txt`.
4. Remove `app.state.llamaindex_llm` from `app/main.py`.
5. Zero changes needed in endpoints, models, or the retrieval layer.

---

## Manual Configuration Required

### 1. Install dependencies

The packages are now in `requirements/base.txt`. Install them into the venv:

```bash
cd backend
.venv/bin/pip install llama-index-core==0.12.6 llama-index-llms-ollama==0.5.0
```

### 2. Confirm Ollama model is available

The synthesis LLM uses `OLLAMA_CHAT_MODEL` (default: `qwen2.5`). Confirm it is pulled:

```bash
ollama list
# should show qwen2.5 (or whatever model you configured)
```

If not:
```bash
ollama pull qwen2.5
```

### 3. Optional `.env` overrides

```env
# Which LlamaIndex response mode to use
SYNTHESIS_MODE=compact          # compact | refine | tree_summarize

# Inherited by both OllamaService and LlamaIndexOllama
OLLAMA_CHAT_MODEL=qwen2.5
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_CHAT_TIMEOUT=120.0
```

---

## How to Test the Changes

### Prerequisites

Qdrant must be running and the vault must be indexed (`POST /api/v1/ingest` first).

```bash
docker compose up -d qdrant
cd backend && .venv/bin/uvicorn app.main:app --reload
```

### 1. Basic RAG chat

```bash
curl -s -X POST http://localhost:8000/api/v1/chat/rag \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What is machine learning?"}]
  }' | jq .
```

Expected shape:
```json
{
  "id": "...",
  "role": "assistant",
  "content": "Machine learning is ...",
  "sources": [
    {"note_title": "...", "note_path": "...", "excerpt": "...", "score": 0.87}
  ],
  "retrieval_latency_ms": 185.2,
  "synthesis_latency_ms": 2341.0,
  "total_candidates": 15,
  "deduplicated_count": 2,
  "filters_applied": false,
  "created_at": "..."
}
```

### 2. With score threshold — higher precision

```bash
curl -s -X POST http://localhost:8000/api/v1/chat/rag \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Explain transformers"}],
    "score_threshold": 0.7
  }' | jq '.content, .sources | length'
```

### 3. With tag filter

```bash
curl -s -X POST http://localhost:8000/api/v1/chat/rag \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What notes do I have about Python?"}],
    "tags": ["python"],
    "top_k": 5
  }' | jq '.filters_applied, (.sources | length)'
# → true, N
```

### 4. No relevant notes (fallback message)

```bash
curl -s -X POST http://localhost:8000/api/v1/chat/rag \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "xyzzy frobnicator quantum banana"}],
    "score_threshold": 0.99
  }' | jq '.content'
# → "I couldn't find any relevant information..."
```

### 5. Verify plain /chat is unchanged

```bash
curl -s -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}]}' | jq '.content'
# → Works as before, no sources
```

### 6. Compare refine vs compact mode

Set `SYNTHESIS_MODE=refine` in `.env`, restart, run the same query, compare latency and answer quality. Refine is slower but produces better answers when retrieved chunks are long.

### 7. Unit tests only (no live services)

```bash
cd backend
.venv/bin/python -m pytest tests/services/synthesis/ -v
# → 16 passed
```

### 8. Full suite

```bash
.venv/bin/python -m pytest
# → 248 passed
```

---

## Test Results

```
248 passed in 2.19s
```

All tests pass with no live external services required for the unit suite.
