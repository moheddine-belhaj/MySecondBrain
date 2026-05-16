"""Ollama provider — concrete implementation of LLMProvider + EmbeddingProvider.

Ollama API reference
--------------------
POST /api/chat          → chat completion (stream or blocking)
POST /api/embed         → embeddings (single or batch input)
GET  /api/tags          → list downloaded models (used for health check)

Wire format — streaming chat
Each line from the response stream is a newline-delimited JSON object:
  {"model": "...", "message": {"role": "assistant", "content": "token"}, "done": false}
  ...
  {"model": "...", "message": {"role": "assistant", "content": ""}, "done": true, "total_duration": 123}

Wire format — embed response
  {"model": "...", "embeddings": [[0.1, 0.2, ...]], "total_duration": 123}
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import AsyncIterator, TypeVar

import httpx

from app.exceptions import ServiceUnavailableError
from app.services.llm.base import EmbeddingProvider, LLMProvider
from app.services.llm.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    StreamDelta,
)

logger = logging.getLogger("app.services.ollama")

T = TypeVar("T")

# Exceptions that indicate a transient connectivity failure worth retrying.
# ReadTimeout is excluded — a slow model is not a transient failure; retrying
# would just double the load and likely time out again.
_RETRYABLE = (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError)


async def _retry(
    operation: Callable[[], Awaitable[T]],
    max_retries: int,
    base_delay: float,
    label: str,
) -> T:
    """Run `operation` with exponential back-off on transient errors.

    Delays: 0.5 s → 1.0 s → 2.0 s (with max_retries=3, base_delay=0.5)
    Only retries _RETRYABLE exceptions — does not swallow read timeouts or 4xx.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return await operation()  # type: ignore[return-value]
        except _RETRYABLE as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Ollama connection failed, retrying",
                    extra={"label": label, "attempt": attempt + 1, "delay_s": delay},
                )
                await asyncio.sleep(delay)
    raise ServiceUnavailableError("Ollama", str(last_exc))


class OllamaService(LLMProvider, EmbeddingProvider):
    """Stateless wrapper around the Ollama HTTP API.

    Two separate httpx clients are injected (created in main.py lifespan):
      _chat_client  — long read timeout (generation is slow on CPU)
      _embed_client — short read timeout (embedding is fast)

    Both clients share the same connection pool implementation and base_url;
    the only difference is the timeout profile. Keeping them separate avoids
    embedding requests blocking on a stalled generation timeout and vice versa.

    Thread safety: httpx.AsyncClient is safe to share across coroutines.
    """

    def __init__(
        self,
        chat_client: httpx.AsyncClient,
        embed_client: httpx.AsyncClient,
        chat_model: str = "qwen2.5",
        embed_model: str = "nomic-embed-text",
        max_retries: int = 3,
        retry_delay: float = 0.5,
    ) -> None:
        self._chat_client = chat_client
        self._embed_client = embed_client
        self.chat_model = chat_model
        self.embed_model = embed_model
        self._max_retries = max_retries
        self._retry_delay = retry_delay

    # ── LLMProvider ───────────────────────────────────────────────────────────

    async def chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        """Blocking chat — waits for the complete response before returning.

        Use this for short requests or when the caller cannot consume a stream.
        """
        payload = self._build_chat_payload(request, stream=False)

        async def _call() -> ChatCompletionResponse:
            response = await self._chat_client.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
            return ChatCompletionResponse(
                model=data["model"],
                content=data["message"]["content"],
                prompt_tokens=data.get("prompt_eval_count"),
                completion_tokens=data.get("eval_count"),
                total_duration_ms=_ns_to_ms(data.get("total_duration")),
            )

        logger.info(
            "Chat request",
            extra={"model": request.model, "turns": len(request.messages)},
        )
        return await _retry(_call, self._max_retries, self._retry_delay, "chat")

    async def chat_stream(  # type: ignore[override]
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[StreamDelta]:
        # This method is declared as returning AsyncIterator in the ABC.
        # The implementation is an async generator (subtype of AsyncIterator).
        return self._stream_generator(request)

    async def _stream_generator(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[StreamDelta]:
        """Async generator that yields deltas from the Ollama streaming API.

        Retry logic applies only to the initial connection. If the stream
        breaks mid-response, we emit a done=True event and stop — partial
        responses are better than silently hanging.
        """
        payload = self._build_chat_payload(request, stream=True)
        last_exc: Exception | None = None

        for attempt in range(self._max_retries):
            try:
                async with self._chat_client.stream("POST", "/api/chat", json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        data = json.loads(line)
                        content = data.get("message", {}).get("content", "")
                        done = data.get("done", False)
                        yield StreamDelta(content=content, done=done)
                        if done:
                            return
                return  # clean exit from the generator
            except _RETRYABLE as exc:
                last_exc = exc
                if attempt < self._max_retries - 1:
                    delay = self._retry_delay * (2**attempt)
                    logger.warning(
                        "Stream connection failed, retrying",
                        extra={"attempt": attempt + 1, "delay_s": delay},
                    )
                    await asyncio.sleep(delay)
            except Exception as exc:
                logger.error("Stream error mid-response", extra={"error": str(exc)})
                yield StreamDelta(content="", done=True)
                return

        raise ServiceUnavailableError("Ollama", str(last_exc))

    async def health(self) -> bool:
        try:
            r = await self._chat_client.get("/api/tags")
            return r.status_code == 200
        except Exception:
            return False

    # ── EmbeddingProvider ─────────────────────────────────────────────────────

    async def embed(self, text: str) -> list[float]:
        """Embed a single string. Returns the raw float vector."""
        response = await self._embed(EmbeddingRequest(model=self.embed_model, input=text))
        return response.embeddings[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of strings in one round-trip.

        Ollama's /api/embed accepts a list as `input`, so this is a single
        HTTP request regardless of how many texts are passed.
        """
        response = await self._embed(EmbeddingRequest(model=self.embed_model, input=texts))
        return response.embeddings

    async def _embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        payload = {"model": request.model, "input": request.input}

        async def _call() -> EmbeddingResponse:
            response = await self._embed_client.post("/api/embed", json=payload)
            response.raise_for_status()
            data = response.json()
            return EmbeddingResponse(
                model=data["model"],
                embeddings=data["embeddings"],
                total_duration_ms=_ns_to_ms(data.get("total_duration")),
            )

        logger.info("Embed request", extra={"model": request.model})
        return await _retry(_call, self._max_retries, self._retry_delay, "embed")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_chat_payload(
        self, request: ChatCompletionRequest, stream: bool
    ) -> dict:
        opts = request.options
        payload: dict = {
            "model": request.model,
            "messages": [
                {"role": m.role, "content": m.content} for m in request.messages
            ],
            "stream": stream,
            "options": {
                "temperature": opts.temperature,
                "num_predict": opts.max_tokens,
                "top_p": opts.top_p,
            },
        }
        if opts.stop:
            payload["options"]["stop"] = opts.stop
        return payload


def _ns_to_ms(ns: int | None) -> float | None:
    """Convert Ollama's nanosecond durations to milliseconds."""
    return round(ns / 1_000_000, 2) if ns is not None else None
