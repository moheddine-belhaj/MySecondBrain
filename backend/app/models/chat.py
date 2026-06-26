from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


# ── Shared primitives ─────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class NoteSource(BaseModel):
    note_title: str
    note_path: str
    excerpt: str
    score: float


# ── SSE event protocol ────────────────────────────────────────────────────────
# Every event sent over the stream is one of these four types.
# Wire format:  data: <JSON>\n\n
#
# Event flow for /chat/rag/stream:
#   1. "retrieval" — sent immediately after vector search completes;
#      lets the frontend render source cards while the answer still streams.
#   2. "delta"     — one per token (or small chunk); done=false.
#   3. "done"      — final event; done=true; carries session_id and full sources.
#   4. "error"     — terminal; sent instead of "done" when something goes wrong.
#
# For /chat/stream (no RAG) the flow is just: delta* → done.

class StreamEventType(str, Enum):
    RETRIEVAL = "retrieval"
    DELTA = "delta"
    DONE = "done"
    ERROR = "error"


class StreamEvent(BaseModel):
    """One SSE payload object."""

    type: StreamEventType
    delta: str = ""
    done: bool = False
    session_id: str | None = None
    message_id: str | None = None
    sources: list[NoteSource] = []
    candidate_count: int = 0
    error: str = ""


# ── Plain chat ────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1)
    session_id: str | None = Field(
        default=None,
        description="Reuse an existing session to carry conversation history. "
                    "Omit to start a new session (a fresh UUID is returned).",
    )


class ChatResponse(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    role: Literal["assistant"] = "assistant"
    content: str
    sources: list[NoteSource] = []
    session_id: str | None = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ── RAG chat ──────────────────────────────────────────────────────────────────

class RagChatRequest(BaseModel):
    """RAG-enabled chat request.

    The last message in `messages` is used as the retrieval query.
    All prior messages are ignored for retrieval but available in session history.
    """

    messages: list[ChatMessage] = Field(..., min_length=1)
    session_id: str | None = Field(
        default=None,
        description="Session ID for conversation memory. Auto-created if omitted.",
    )
    top_k: int = Field(default=5, ge=1, le=20, description="Max chunks to retrieve")
    score_threshold: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Minimum similarity score"
    )
    tags: list[str] | None = Field(default=None, description="Filter by tags (OR match)")
    note_path: str | None = Field(default=None, description="Filter by exact note path")
    deduplicate: bool = Field(
        default=True, description="Deduplicate chunks from the same heading/note"
    )


class RagChatResponse(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    role: Literal["assistant"] = "assistant"
    content: str
    sources: list[NoteSource] = []
    session_id: str | None = None
    retrieval_latency_ms: float
    synthesis_latency_ms: float
    total_candidates: int
    deduplicated_count: int
    filters_applied: bool
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ── Session management ────────────────────────────────────────────────────────

class SessionMessageOut(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    timestamp: float


class SessionInfo(BaseModel):
    session_id: str
    message_count: int
    created_at: float
    last_active: float


class ConversationHistory(BaseModel):
    session_id: str
    messages: list[SessionMessageOut]
    created_at: float
    last_active: float
