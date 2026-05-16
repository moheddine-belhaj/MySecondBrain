# Task 3 — API Layer & Local Testing

## Goal

Make every API endpoint testable right now, without requiring Qdrant, Ollama, or
any AI dependency to be running. This means:

1. Add Pydantic request/response models for all three domain areas.
2. Add stub route handlers to every endpoint so HTTP requests return typed responses.
3. Create a minimal `requirements/server.txt` so the venv can be set up instantly.
4. Create a Postman collection covering all routes including validation edge cases.
5. Verify the server imports and starts cleanly.

---

## Problem with the Task 1 Endpoint Stubs

After Task 1, the three router files each contained only:

```python
from fastapi import APIRouter
router = APIRouter()
# Task N — implementation
```

There were no route decorators. Hitting `/api/v1/chat` returned 405 Method Not
Allowed. There was nothing to test.

---

## Files Created / Modified

```
backend/
├── app/
│   ├── models/
│   │   ├── chat.py        ← new
│   │   ├── ingest.py      ← new
│   │   └── search.py      ← new
│   └── api/v1/endpoints/
│       ├── chat.py        ← updated
│       ├── ingest.py      ← updated
│       └── search.py      ← updated
└── requirements/
    └── server.txt         ← new

docs/
└── second-brain.postman_collection.json   ← new
```

---

## Pydantic Models

### `backend/app/models/chat.py`

```python
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, Field

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str

class NoteSource(BaseModel):
    note_title: str
    note_path: str
    excerpt: str
    score: float

class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1)

class ChatResponse(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    role: Literal["assistant"] = "assistant"
    content: str
    sources: list[NoteSource] = []
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
```

**Decisions:**
- `role: Literal["user", "assistant"]` — Pydantic rejects any other string value
  at the boundary with a clear error. No manual validation needed.
- `messages: list[ChatMessage] = Field(..., min_length=1)` — An empty messages
  array has no meaning for a chat endpoint. `min_length=1` returns 422 with a
  descriptive error rather than passing an empty list into the LLM.
- `id` and `created_at` have server-side defaults — the client never generates
  these, so they must not be required in the request body.
- `sources: list[NoteSource] = []` — Default empty list; populated once the RAG
  pipeline is wired in Task 4.

---

### `backend/app/models/ingest.py`

```python
from typing import Literal
from pydantic import BaseModel

class IngestStatus(BaseModel):
    status: Literal["pending", "running", "completed", "failed"]
    total_notes: int = 0
    processed_notes: int = 0
    message: str | None = None
```

The four status values map to the ingestion state machine:
- `pending` — no run has started
- `running` — actively reading and embedding notes
- `completed` — all notes processed
- `failed` — an error occurred (message field carries the reason)

---

### `backend/app/models/search.py`

```python
from pydantic import BaseModel

class SearchResult(BaseModel):
    note_title: str
    note_path: str
    excerpt: str
    score: float
```

Mirrors the shape returned by Qdrant's scored points. `score` is the cosine
similarity between the query embedding and the chunk embedding.

---

## Endpoint Handlers

### `backend/app/api/v1/endpoints/chat.py`

```python
from fastapi import APIRouter
from app.models.chat import ChatRequest, ChatResponse

router = APIRouter()

@router.post("", response_model=ChatResponse, summary="Send a chat message")
async def chat(request: ChatRequest) -> ChatResponse:
    # Stub — RAG pipeline wired in Task 4
    last_user_msg = next(
        (m.content for m in reversed(request.messages) if m.role == "user"), ""
    )
    return ChatResponse(
        content=f'[stub] You asked: "{last_user_msg}". RAG pipeline coming in Task 4.',
        sources=[],
    )
```

The stub echoes the last user message back. This lets you verify that:
- JSON deserialization works (request body parsed correctly)
- Pydantic validation fires (bad requests return 422)
- The response schema is correct (all required fields present, correct types)

---

### `backend/app/api/v1/endpoints/ingest.py`

```python
from fastapi import APIRouter
from app.models.ingest import IngestStatus

router = APIRouter()

@router.post("", response_model=IngestStatus, summary="Trigger vault ingestion")
async def trigger_ingest() -> IngestStatus:
    return IngestStatus(
        status="pending",
        message="Ingestion pipeline not yet implemented. Coming in Task 4.",
    )

@router.get("/status", response_model=IngestStatus, summary="Get ingestion status")
async def ingest_status() -> IngestStatus:
    return IngestStatus(status="pending", message="No ingestion run yet.")
```

Two routes:
- `POST /ingest` — triggers an ingestion job (returns current status)
- `GET /ingest/status` — polls the status of a running job

The poll pattern (`POST → GET /status`) is used because ingestion is
asynchronous. The `POST` starts the job and returns immediately; the client polls
`/status` until `completed` or `failed`.

---

### `backend/app/api/v1/endpoints/search.py`

```python
from fastapi import APIRouter, Query
from app.models.search import SearchResult

router = APIRouter()

@router.get("", response_model=list[SearchResult], summary="Semantic search over vault")
async def search(
    q: str = Query(..., min_length=1, description="Natural language search query"),
) -> list[SearchResult]:
    return []
```

- `q` is a required query parameter (`...` means no default).
- `min_length=1` prevents an empty string from reaching the embedding layer.
- Returns an empty list until Qdrant retrieval is wired in Task 4.

---

## `requirements/server.txt`

```
fastapi==0.115.5
uvicorn[standard]==0.32.1
pydantic==2.10.3
pydantic-settings==2.6.1
python-multipart==0.0.20
```

`base.txt` includes LlamaIndex, Qdrant client, and Ollama client — these are
multi-GB install chains that are not needed to run the API layer alone. The
`server.txt` file installs only what FastAPI needs, so the venv is ready in
under 30 seconds.

---

## Venv Setup

```bash
cd backend

# Create and activate
python3 -m venv .venv
source .venv/bin/activate

# Install server deps only (no AI stack)
pip install -r requirements/server.txt

# Create local env file with debug enabled
cp .env.example .env
# Edit .env and set: DEBUG=true

# Start with hot reload
uvicorn app.main:app --reload
```

Expected output:
```
INFO:     Will watch for changes in these directories: ['...']
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Application startup complete.
```

**Why `DEBUG=true`?**
The app factory in `main.py` gates the Swagger UI behind the debug flag:
```python
docs_url="/docs" if settings.debug else None,
```
Without it, `GET /docs` returns 404.

---

## Live Routes

After starting the server, all of the following respond:

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Server liveness |
| `GET` | `/docs` | Swagger UI (requires `DEBUG=true`) |
| `POST` | `/api/v1/chat` | Chat with the assistant |
| `POST` | `/api/v1/ingest` | Trigger vault ingestion |
| `GET` | `/api/v1/ingest/status` | Poll ingestion status |
| `GET` | `/api/v1/search?q=...` | Semantic search |

---

## curl Test Examples

```bash
# Health
curl http://localhost:8000/health
# → {"status":"ok","version":"0.1.0"}

# Chat — single turn
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is Zettelkasten?"}]}'
# → {"id":"...","role":"assistant","content":"[stub]...","sources":[],"created_at":"..."}

# Chat — empty messages (validation test)
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": []}'
# → 422 Unprocessable Entity

# Trigger ingest
curl -X POST http://localhost:8000/api/v1/ingest
# → {"status":"pending","total_notes":0,"processed_notes":0,"message":"..."}

# Ingest status
curl http://localhost:8000/api/v1/ingest/status
# → {"status":"pending",...}

# Search
curl "http://localhost:8000/api/v1/search?q=Zettelkasten"
# → []

# Search — empty query (validation test)
curl "http://localhost:8000/api/v1/search?q="
# → 422 Unprocessable Entity
```

---

## Postman Collection

File: `docs/second-brain.postman_collection.json`

**Import:** Postman → Import → select the file.

The collection uses a `{{base_url}}` variable (default: `http://localhost:8000`).
To run against a different host, change the variable in Collection → Variables.

### Requests Included

| Folder | Request | Expected Status |
|---|---|---|
| Health | Health Check | 200 |
| Chat | Send Message (single turn) | 200 |
| Chat | Send Message (multi turn) | 200 |
| Chat | Validation — empty messages | 422 |
| Chat | Validation — missing role | 422 |
| Ingest | Trigger Ingestion | 200 |
| Ingest | Get Ingestion Status | 200 |
| Search | Semantic Search | 200 |
| Search | Validation — empty query | 422 |
| Search | Validation — missing query param | 422 |

Every request has a Postman test script that asserts the status code and
validates the response shape. Run them via **Collection → Run** to get a pass/fail
report across all 10 requests.

### Example Test Script (Chat)

```javascript
pm.test('Status 200', () => pm.response.to.have.status(200));
pm.test('Response has required fields', () => {
  const body = pm.response.json();
  pm.expect(body).to.have.property('id');
  pm.expect(body.role).to.eql('assistant');
  pm.expect(body.content).to.be.a('string');
  pm.expect(body.sources).to.be.an('array');
  pm.expect(body.created_at).to.be.a('string');
});
```

---

## Verification

The server import was verified to be clean with no errors:

```bash
DEBUG=true .venv/bin/python -c \
  "from app.main import app; print([r.path for r in app.routes])"
```

Output:
```
['/openapi.json', '/docs', '/docs/oauth2-redirect', '/redoc',
 '/api/v1/chat', '/api/v1/ingest', '/api/v1/ingest/status',
 '/api/v1/search', '/health']
```

All 9 routes registered. No import errors.

---

## What This Task Enables

- Every endpoint responds to HTTP requests and returns a typed JSON body.
- Pydantic validates every request at the boundary — bad payloads never reach
  business logic.
- The entire API contract (request shapes, response shapes, status codes) is
  visible in Swagger UI and the Postman collection before any AI logic is written.
- Other team members or the portfolio reviewer can explore the API immediately.

## What Is NOT Done Here

- No actual AI logic — all handlers return stubs.
- No Qdrant or Ollama connection — not needed until Task 4.
- No authentication — planned for a later security task.
- No streaming chat response — planned when the RAG pipeline is wired.
