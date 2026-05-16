"""Abstract provider contracts.

Why ABCs and not Protocols?

Protocols give structural subtyping ("duck typing") — any class that has the
right methods qualifies automatically. ABCs give nominal subtyping — you must
explicitly subclass and implement every @abstractmethod.

For provider swap-outs (Ollama → OpenAI → Anthropic), nominal subtyping is
better: a missing method is caught at class definition time, not at the call
site at runtime. ABCs also let IDEs and mypy verify completeness.

Adding a new provider:
1. Subclass LLMProvider (or EmbeddingProvider, or both)
2. Implement all abstract methods
3. Change the lifespan in main.py to instantiate your new class
4. Zero endpoint changes required
"""

from abc import ABC, abstractmethod
from typing import AsyncIterator

from app.services.llm.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    StreamDelta,
)


class LLMProvider(ABC):
    """Contract for any text-generation backend."""

    @abstractmethod
    async def chat(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """Blocking chat completion — waits for the full response."""
        ...

    @abstractmethod
    def chat_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[StreamDelta]:
        """Return an async iterator that yields tokens as they arrive.

        Declared as a plain `def` (not `async def`) so the ABC doesn't force
        implementations into a specific coroutine shape. Implementations use
        `async def ... yield` (AsyncGenerator), which is a subtype of
        AsyncIterator and satisfies the contract.
        """
        ...

    @abstractmethod
    async def health(self) -> bool:
        """Return True if the provider is reachable and serving requests."""
        ...


class EmbeddingProvider(ABC):
    """Contract for any vector embedding backend."""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Embed a single text string. Returns the embedding vector."""
        ...

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in one round-trip. More efficient than N embed() calls."""
        ...

    @abstractmethod
    async def health(self) -> bool:
        ...
