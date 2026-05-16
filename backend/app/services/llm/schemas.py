"""Internal LLM schemas — these are NOT the API request/response models.

Separation of concerns:
  app/models/      → HTTP boundary shapes (what the client sends/receives)
  app/services/llm/schemas.py → what the service layer works with internally

This means the API contract and the LLM provider contract can evolve
independently. For example, adding streaming metadata to the provider
response doesn't force a breaking change to the public API.
"""

from typing import Literal

from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    """Provider-level message — adds 'system' role that the public API hides.

    Clients never send system messages; they are injected server-side by the
    prompt assembly layer (implemented in a later task). Keeping system out of
    the public API prevents prompt injection from the client side.
    """

    role: Literal["user", "assistant", "system"]
    content: str


class LLMOptions(BaseModel):
    """Generation parameters. Defaults chosen for a RAG use-case:
    - temperature 0.3: factual, low creativity — we want grounded answers
    - top_p 0.9: broad enough vocabulary, cuts off the long tail
    - max_tokens 2048: enough for a detailed answer with citations
    """

    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, gt=0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    stop: list[str] = []


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[LLMMessage]
    options: LLMOptions = LLMOptions()


class ChatCompletionResponse(BaseModel):
    model: str
    content: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_duration_ms: float | None = None


class StreamDelta(BaseModel):
    """A single chunk of a streaming response.

    content  — the next token(s); empty string on the final event
    done     — True on the last event; the consumer should stop reading
    """

    content: str
    done: bool


class EmbeddingRequest(BaseModel):
    model: str
    input: str | list[str]


class EmbeddingResponse(BaseModel):
    model: str
    embeddings: list[list[float]]
    total_duration_ms: float | None = None
