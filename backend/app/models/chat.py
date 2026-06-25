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


class RagChatRequest(BaseModel):
    """RAG-enabled chat request.

    The last message in `messages` is used as the retrieval query.
    All prior messages provide conversation history (for context, not retrieval).
    """

    messages: list[ChatMessage] = Field(..., min_length=1)
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
    retrieval_latency_ms: float
    synthesis_latency_ms: float
    total_candidates: int
    deduplicated_count: int
    filters_applied: bool
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
