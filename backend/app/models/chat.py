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
