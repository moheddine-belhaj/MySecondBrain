# Task 12 — Streaming Chat API

## What Was Built

A fully frontend-ready streaming chat layer with four endpoints, conversation session memory, SSE-based streaming for both plain and RAG chat, cancellation support, and per-session history management.

---

## New Files

| File | Role |
|---|---|
| `app/services/session/store.py` | In-memory session store: TTL eviction, LRU cap, history trimming |
| `app/services/session/__init__.py` | Package export |
| `tests/services/session/test_store.py` | 27 tests for SessionStore |

## Modified Files

| File | Change |
|---|---|
| `app/models/chat.py` | Added `StreamEvent`, `StreamEventType`, `SessionInfo`, `ConversationHistory`, `SessionMessageOut`; added `session_id` to request models |
| `app/api/v1/endpoints/chat.py` | Full rewrite — 6 endpoints, streaming RAG, session memory, cancellation |
| `app/dependencies.py` | Added `get_session_store`, `SessionDep` |
| `app/main.py` | Init `SessionStore` on `app.state` during lifespan |
| `app/services/synthesis/prompts.py` | Added `build_rag_user_message()` helper for streaming path |

**Test count: 296 → 323 (+27)**

---

## Endpoint Map

| Method | Path | Type | Description |
|---|---|---|---|
| `POST` | `/api/v1/chat` | Blocking | Plain chat with session memory |
| `POST` | `/api/v1/chat/stream` | SSE | Streaming plain chat |
| `POST` | `/api/v1/chat/rag` | Blocking | RAG chat (retrieval + synthesis) |
| `POST` | `/api/v1/chat/rag/stream` | SSE | **New** — streaming RAG with retrieval event |
| `GET` | `/api/v1/chat/sessions/{id}` | JSON | Fetch conversation history |
| `DELETE` | `/api/v1/chat/sessions/{id}` | JSON | Clear a session |

---

## Architecture

### SSE Event Protocol

Every streaming endpoint sends `data: <JSON>\n\n` events. The JSON is always a `StreamEvent`:

```typescript
type StreamEventType = "retrieval" | "delta" | "done" | "error"

interface StreamEvent {
  type: StreamEventType
  delta: string           // token content (delta events)
  done: boolean           // true on "done" and "error"
  session_id?: string     // present on "done"
  message_id?: string
  sources: NoteSource[]   // present on "retrieval" and "done"
  candidate_count: number // present on "retrieval"
  error: string           // present on "error"
}
```

**Event sequence for `/chat/rag/stream`:**

```
→ {"type": "retrieval", "sources": [...], "candidate_count": 12}
→ {"type": "delta", "delta": "Moheddine", "done": false}
→ {"type": "delta", "delta": " is a", "done": false}
  ... (one per token)
→ {"type": "done", "done": true, "session_id": "...", "sources": [...]}
```

Emitting `retrieval` before generation lets the frontend render source cards instantly while the model is still warming up — the user sees where the answer is coming from before reading it.

**Event sequence for `/chat/stream`:**

```
→ {"type": "delta", "delta": "token", "done": false}
  ...
→ {"type": "done", "done": true, "session_id": "..."}
```

---

### Why SSE over WebSockets

| | SSE | WebSocket |
|---|---|---|
| Protocol | HTTP/1.1 | Upgrade → ws:// |
| Direction | Server → client only | Bidirectional |
| Reconnect | Built-in (browser auto-reconnects) | Manual |
| Proxy/CDN | Works transparently | Requires ws support |
| Client | `fetch` + `ReadableStream` or `EventSource` | `new WebSocket()` |
| Complexity | Low | Higher |

SSE is the right choice here: the server generates tokens, the client only sends requests. Bidirectional communication adds no value for a chat API where each user turn is a new HTTP request.

> **Note:** `EventSource` only supports GET. Use `fetch` with `ReadableStream` for `POST /chat/rag/stream` (which sends a request body).

---

### Streaming RAG vs Blocking RAG

The blocking `/chat/rag` path uses **LlamaIndex** (`asynthesize()`): it packs context, fills the template, and calls Ollama — all before returning.

The streaming `/chat/rag/stream` path **bypasses LlamaIndex** for generation:

```
POST /chat/rag/stream
       │
       ▼
RetrievalEngine.retrieve()          ← unchanged
       │  list[RetrievedChunk]
       ▼
ContextBuilder.build()              ← same as blocking path
       │  BuiltContext.context_str
       ▼
build_rag_user_message()            ← prompts.py — same layer constants as QA_PROMPT
       │  context-injected user message
       ▼
_build_rag_messages()               ← SYSTEM_INSTRUCTIONS + session history + user turn
       │  list[LLMMessage]
       ▼
llm.chat_stream()                   ← OllamaService directly (token-by-token)
       │  AsyncIterator[StreamDelta]
       ▼
SSE stream → client
```

Both paths use identical `SYSTEM_INSTRUCTIONS`, the same citation format from `ContextBuilder`, and the same token budget from `PromptConfig`. The only difference is who calls Ollama: LlamaIndex (blocking) vs OllamaService (streaming).

---

### Session Memory

```
SessionStore (singleton on app.state)
├── max_sessions = 100     (LRU eviction)
├── max_history  = 20      (messages per session, oldest trimmed)
└── ttl_seconds  = 3600    (1 hour idle expiry)

ConversationSession
├── session_id: str (UUID4)
├── messages: list[ConversationMessage]
├── created_at: float (unix timestamp)
└── last_active: float (updated on every access)
```

**How history is injected into the LLM:**

```
System message (always first)
  ↓
Last 10 prior turns (20 messages) from session
  ↓
Current user message (with context for RAG, raw for plain)
```

Only the last `_MAX_HISTORY_TURNS * 2 = 20` messages are sent to the LLM per request. Older messages remain in the session (for GET /sessions) but are not in the prompt.

**Eviction:**
- **TTL**: sessions not accessed for >1 hour are cleaned up lazily on the next `get_or_create()` call.
- **LRU cap**: if 100 sessions are active, the least-recently-used one is evicted to make room.
- **History trim**: when a session exceeds 20 messages, the oldest ones are dropped. Most-recent messages always survive.

---

### Cancellation

Both streaming endpoints check `await request.is_disconnected()` in their generator loop between every token:

```python
async for delta in stream:
    if await request.is_disconnected():
        logger.info("Client disconnected mid-stream")
        return   # generator exits; StreamingResponse closes cleanly
    yield _sse(...)
```

When the client closes the connection (tab closed, network drop, `AbortController`):
- The generator returns early.
- The partial answer is **not** saved to the session (an incomplete turn confuses follow-up queries).
- The Ollama stream is abandoned — Ollama keeps generating briefly but the tokens are discarded.

---

### Request Validation

All request models use Pydantic v2 with Field constraints:

| Field | Validation |
|---|---|
| `messages` | `min_length=1` — at least one message required |
| `top_k` | `ge=1, le=20` — between 1 and 20 chunks |
| `score_threshold` | `ge=0.0, le=1.0` — valid cosine similarity range |
| `session_id` | `str | None` — optional UUID; server validates existence on GET/DELETE |

FastAPI returns `422 Unprocessable Entity` automatically for constraint violations.

---

### Conversation History Injection — Security Note

The public `ChatRequest.messages` field accepts only `"user"` and `"assistant"` roles. System prompts are **always injected server-side** — clients cannot override `SYSTEM_INSTRUCTIONS` or the RAG anti-hallucination rules. This prevents prompt injection from the API consumer.

---

## Session Management

### Create / reuse a session

Every `POST /chat`, `POST /chat/stream`, `POST /chat/rag`, and `POST /chat/rag/stream` accepts:

```json
{ "session_id": "my-session-uuid" }
```

If omitted → a new session is auto-created. The session ID is returned in:
- `ChatResponse.session_id`
- `RagChatResponse.session_id`
- The `"done"` SSE event: `{"type": "done", "session_id": "..."}`

### Fetch history

```
GET /api/v1/chat/sessions/{session_id}
```

Response:
```json
{
  "session_id": "...",
  "messages": [
    {"role": "user",      "content": "who is moheddine?", "timestamp": 1719000000.0},
    {"role": "assistant", "content": "Moheddine is ...",  "timestamp": 1719000001.2}
  ],
  "created_at": 1719000000.0,
  "last_active": 1719000001.2
}
```

### Clear a session

```
DELETE /api/v1/chat/sessions/{session_id}
```

Returns the final `SessionInfo` (message count, timestamps) before deletion.

---

## Tests

| Test file | Tests | What's covered |
|---|---|---|
| `tests/services/session/test_store.py` | 27 | `get_or_create`, `get`, `add_message`, `delete`, `count`, TTL eviction, LRU eviction, history trimming |

All tests are pure Python — no FastAPI, no Ollama, no Qdrant.

---

## Manual Testing Guide

### 1. Start services and server

```bash
docker run -p 6333:6333 qdrant/qdrant          # terminal 1
ollama serve                                     # terminal 2
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000  # terminal 3
```

### 2. Ingest vault

```bash
curl -s -X POST http://localhost:8000/api/v1/ingest | python3 -m json.tool
```

### 3. Test streaming RAG (core new endpoint)

```bash
curl -s -X POST http://localhost:8000/api/v1/chat/rag/stream \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "who is moheddine?"}], "top_k": 3}'
```

Expected output — three event types in order:
```
data: {"type": "retrieval", "sources": [...], "candidate_count": 3, ...}

data: {"type": "delta", "delta": "Moheddine", "done": false, ...}
data: {"type": "delta", "delta": " is a", "done": false, ...}
...
data: {"type": "done", "done": true, "session_id": "uuid-here", "sources": [...], ...}
```

### 4. Test session memory (multi-turn)

```bash
# Turn 1 — save the session_id from the response
SESSION=$(curl -s -X POST http://localhost:8000/api/v1/chat/rag \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "who is moheddine?"}]}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")

echo "Session: $SESSION"

# Turn 2 — follow-up using the session; model remembers the context
curl -s -X POST http://localhost:8000/api/v1/chat/rag \
  -H "Content-Type: application/json" \
  -d "{\"messages\": [{\"role\": \"user\", \"content\": \"what are his skills?\"}], \"session_id\": \"$SESSION\"}" \
  | python3 -m json.tool
```

### 5. Fetch session history

```bash
curl -s "http://localhost:8000/api/v1/chat/sessions/$SESSION" | python3 -m json.tool
```

### 6. Delete session

```bash
curl -s -X DELETE "http://localhost:8000/api/v1/chat/sessions/$SESSION" | python3 -m json.tool
```

### 7. Test plain streaming

```bash
curl -s -X POST http://localhost:8000/api/v1/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "what is RAG?"}]}'
```

### 8. Verify cancellation

Open the stream in one terminal, then kill it with Ctrl+C mid-stream. The server log should show:
```
INFO  Client disconnected mid-stream  session_id=...
```

---

## Frontend Integration Guide

### Connecting to a streaming endpoint

```javascript
const response = await fetch('/api/v1/chat/rag/stream', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    messages: [{ role: 'user', content: userInput }],
    session_id: currentSessionId,  // null on first turn
    top_k: 5,
  }),
  signal: abortController.signal,  // cancellation
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

let buffer = '';
while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });
  const lines = buffer.split('\n\n');
  buffer = lines.pop() ?? '';  // keep incomplete line

  for (const line of lines) {
    if (!line.startsWith('data: ')) continue;
    const event = JSON.parse(line.slice(6));

    if (event.type === 'retrieval') {
      renderSources(event.sources);
    } else if (event.type === 'delta') {
      appendToken(event.delta);
    } else if (event.type === 'done') {
      currentSessionId = event.session_id;  // save for next turn
      finalizeMessage(event.sources);
    } else if (event.type === 'error') {
      showError(event.error);
    }
  }
}
```

### Cancellation

```javascript
const controller = new AbortController();
// Pass signal to fetch (above)
// Cancel on user action or component unmount:
controller.abort();
```

---

## Manual Configuration

No `.env` changes are required. The session store is configured in `app/main.py` lifespan:

```python
app.state.session_store = SessionStore(
    max_sessions=100,   # max concurrent sessions in memory
    max_history=20,     # max messages stored per session
    ttl_seconds=3600.0, # idle expiry (1 hour)
)
```

To adjust, edit those three values and restart the server. No code changes elsewhere are needed.

The number of history turns sent to the LLM per request is controlled by `_MAX_HISTORY_TURNS = 10` in `app/api/v1/endpoints/chat.py` (10 turns = 20 messages). This is separate from `max_history` in the store: the store keeps 20 messages, the LLM prompt uses the last 20 of those.
