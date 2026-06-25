# Task 11 — Prompt Engineering Layer

## What Was Built

A structured, token-aware prompt orchestration layer that sits between the retrieval pipeline and LlamaIndex. The layer gives full control over what goes into the context window, how sources are cited, and how responses are formatted — without coupling any of this logic to LlamaIndex internals.

---

## New Files

| File | Role |
|---|---|
| `app/services/synthesis/token_counter.py` | Estimates token cost; enforces truncation budgets |
| `app/services/synthesis/context_builder.py` | Formats chunks into numbered citation blocks; enforces token cap |
| `app/services/synthesis/prompt_config.py` | Per-model token budget table; prefix-based model lookup |
| `tests/services/synthesis/test_token_counter.py` | 8 tests |
| `tests/services/synthesis/test_context_builder.py` | 22 tests |
| `tests/services/synthesis/test_prompt_config.py` | 12 tests |

## Modified Files

| File | Change |
|---|---|
| `app/services/synthesis/prompts.py` | Rewritten — three-layer architecture with separated constants |
| `app/services/synthesis/synthesizer.py` | Uses `ContextBuilder`; passes one pre-built node to LlamaIndex |
| `app/dependencies.py` | Wires `ContextBuilder` with model-specific config from `PromptConfig` |
| `tests/services/synthesis/test_synthesizer.py` | Removed obsolete `TestChunkToNode`; updated node-count assertion |

**Test count: 248 → 296 (+48)**

---

## Architecture

### Three-Layer Prompt Design

Every RAG prompt is assembled from three named, independently-testable layers:

```
┌─────────────────────────────────────────────┐
│  Layer 1 · SYSTEM_INSTRUCTIONS              │
│  Persona · Rules · Anti-hallucination        │
│  Citation format · Response format           │
│  Fixed at startup — never changes per request│
└─────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────┐
│  Layer 2 · Context Section                  │
│  Retrieved note excerpts (formatted by       │
│  ContextBuilder, token-capped before here)  │
│  Injected as {context_str} at runtime        │
└─────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────┐
│  Layer 3 · User Section                     │
│  Raw question from the API request           │
│  Injected as {query_str}                    │
└─────────────────────────────────────────────┘
```

Each layer is defined as a named constant in `prompts.py`. They are assembled into LlamaIndex `PromptTemplate` objects at the bottom of the file, keeping the layers visible and independently overridable.

---

## Context Injection Strategy (`context_builder.py`)

### Citation Block Format

Each retrieved chunk becomes a numbered citation block:

```
[1] My Research Note — Key Concepts > Embeddings  (score: 0.92)
────────────────────────────────────────────────────────────────────
chunk body text here …

[2] Another Note  (score: 0.81)
────────────────────────────────────────────────────────────────────
more text …
```

- The `[N]` number maps directly to the model's inline citations (`[1]`, `[2]`) and to the API `sources` list.
- The header shows note title + heading breadcrumb + relevance score.
- The body has the chunker's `[Note: …]` breadcrumb stripped — the citation header already carries that information, and showing it twice wastes tokens.

### Truncation Policy

Chunks are processed in rank order (highest score first):

1. **Chunk fits in remaining budget** → include in full.
2. **Chunk doesn't fit, but ≥ 50 tokens remain** → truncate body to fill remaining budget, set `was_truncated=True`, stop.
3. **Remaining budget < 50 tokens** → skip this chunk and all subsequent ones, stop.

Truncation snaps to the last word boundary and appends ` …` so the model knows content was cut.

---

## Token Counting (`token_counter.py`)

No tokenizer is available at runtime (Ollama doesn't expose a token-counting endpoint). We use the character-based heuristic:

```
tokens ≈ len(text) // 4
```

**4 chars per token** is well-established for English prose (OpenAI's rule of thumb). It slightly underestimates for code (fewer chars/token) and overestimates for CJK (1 char ≈ 1 token). For RAG on English notes this is accurate and conservative — we use slightly less context than the absolute maximum, which is safe.

The heuristic is isolated in one module so it can be replaced with a real tokenizer (e.g. `tiktoken`) by changing only `token_counter.py`.

---

## Per-Model Token Budget (`prompt_config.py`)

Each model has a different context window. `PromptConfig` allocates the total budget across three sections:

| Section | Purpose |
|---|---|
| `system_budget` | Tokens for `SYSTEM_INSTRUCTIONS` (fixed overhead) |
| `context_budget` | Tokens for retrieved note excerpts |
| `response_budget` | Headroom reserved for the model's answer |

### Configured Models

| Model | Context Window | Context Budget |
|---|---|---|
| `qwen2.5` | 32 768 | 6 000 |
| `llama3` | 8 192 | 3 000 |
| `mistral` | 8 192 | 3 000 |
| `phi3` | 4 096 | 1 500 |
| `gemma` | 8 192 | 3 000 |
| `deepseek` | 32 768 | 6 000 |
| `default` | 4 096 | 1 500 |

Model lookup is **prefix-based**: `"qwen2.5:7b"` → `"qwen2.5"` config. Unknown models fall back to `"default"` (conservative 4 k window).

### Wiring in `dependencies.py`

```python
async def get_synthesizer(request: Request) -> ResponseSynthesizer:
    config = get_prompt_config(settings.ollama_chat_model)
    context_builder = ContextBuilder(max_context_tokens=config.context_budget)
    return ResponseSynthesizer(
        llm=request.app.state.llamaindex_llm,
        mode=settings.synthesis_mode,
        context_builder=context_builder,
    )
```

Changing the model in `.env` automatically picks up the correct budget with no code changes.

---

## Prompt Templates (`prompts.py`)

### `QA_PROMPT` (first / only pass)

```
{SYSTEM_INSTRUCTIONS}

Note excerpts from the knowledge base (cite by [N]):
============================================================
{context_str}
============================================================
(End of excerpts — your answer must be grounded in the above only)

Question: {query_str}

Answer (cite each source as [1], [2], etc. — if the context is insufficient, say so explicitly):
```

### `REFINE_PROMPT` (multi-pass overflow)

Used by LlamaIndex when `synthesis_mode = "refine"` or `"tree_summarize"` and the context is split across multiple windows:

```
Original question: {query_str}

Partial answer so far:
{existing_answer}

Additional note excerpts:
============================================================
{context_msg}
============================================================

Refine the answer only if the new excerpts add relevant, non-redundant
information. Otherwise return the existing answer unchanged. Keep citations as [N].

Refined answer:
```

---

## Hallucination Reduction

Five explicit constraints in `SYSTEM_INSTRUCTIONS`:

1. **"Use ONLY the provided excerpts"** — bars outside knowledge or training data.
2. **Mandatory inline citations `[N]`** — every claim must be traceable to a source block.
3. **Explicit refusal instruction** — "say so clearly" rather than guessing when context is thin.
4. **Conciseness rule** — structured output prevents rambling that drifts from context.
5. **Named entity guard** — "Never invent note titles, dates, names, or facts" as a direct command.

The citation format also functions as a mechanical constraint: if the model cites `[3]` but only `[1]` and `[2]` exist, the API consumer can detect the hallucination programmatically.

---

## Synthesizer Flow After This Task

```
POST /api/v1/chat/rag
       │
       ▼
RetrievalEngine.retrieve()          ← unchanged
       │  list[RetrievedChunk]
       ▼
ContextBuilder.build()              ← NEW: formats + caps tokens
       │  BuiltContext
       │    .context_str            → single TextNode
       │    .included_chunks        → SynthesisResult.source_chunks
       │    .total_tokens           → logged for observability
       ▼
LlamaIndex asynthesize()            ← one node, one LLM call
       │  response.response
       ▼
SynthesisResult → RagChatResponse
```

**Before Task 11:** LlamaIndex received N raw `NodeWithScore` objects and handled packing internally. We had no control over context formatting, token budgets, or citation numbering.

**After Task 11:** LlamaIndex receives exactly one pre-built `TextNode`. It only does the Ollama API call and template substitution. We own everything else.

---

## Multi-Model Preparation

The architecture is ready for multiple models with zero code changes:

- **Add a model**: add one entry to `MODEL_CONFIGS` in `prompt_config.py`.
- **Switch models**: change `OLLAMA_CHAT_MODEL` in `.env`. The `get_prompt_config()` lookup picks up the right budget automatically.
- **Per-model prompts**: `get_synthesizer()` in `dependencies.py` can be extended to pass different `QA_PROMPT` / `REFINE_PROMPT` per model. The constants in `prompts.py` are already separated for this.
- **Real tokenizer**: swap `token_counter.py` only. No other module needs to change.

---

## Tests

| Test file | Tests | What's covered |
|---|---|---|
| `test_token_counter.py` | 8 | `estimate_tokens`, `truncate_to_token_budget` |
| `test_context_builder.py` | 22 | `ContextBuilder.build`, `_strip_breadcrumb`, `_format_citation_header` |
| `test_prompt_config.py` | 12 | `get_prompt_config`, all `MODEL_CONFIGS` invariants |
| `test_synthesizer.py` | 9 | `ResponseSynthesizer.synthesize` (updated) |

All tests are pure Python — no Ollama, no Qdrant, no LlamaIndex calls.

---

## Manual Configuration

### `.env` — adjust synthesis settings

```env
# Model must match a key prefix in MODEL_CONFIGS (or "default" is used)
OLLAMA_CHAT_MODEL=qwen2.5

# Response mode: compact | refine | tree_summarize
# compact      — pack all chunks into one prompt; fast, good for most queries
# refine       — iterates chunk-by-chunk, better for large contexts
# tree_summarize — builds a tree of summaries, best for very long vaults
SYNTHESIS_MODE=compact
```

### Adding a new model

Open `app/services/synthesis/prompt_config.py` and add an entry to `MODEL_CONFIGS`:

```python
"my-model": PromptConfig(
    context_window=16_384,   # check the model's actual context size
    system_budget=400,
    context_budget=4_000,
    response_budget=1_024,
),
```

Rule: `system_budget + context_budget + response_budget < context_window` (leave ~10 % headroom).

### Tuning prompts

`SYSTEM_INSTRUCTIONS`, `_CONTEXT_HEADER`, `_CONTEXT_FOOTER`, and `_ANSWER_INSTRUCTION` in `app/services/synthesis/prompts.py` are separate constants. Edit them independently without touching the template assembly at the bottom of the file.
