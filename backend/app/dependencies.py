"""FastAPI dependency providers.

Pattern: endpoints declare `Depends(get_X)` — they never construct resources.
This allows tests to swap any provider without touching endpoint code.

Current providers
-----------------
get_settings           → Settings singleton
get_llm_provider       → LLMProvider (currently OllamaService, stored on app.state)
get_embedding_provider → EmbeddingProvider (same OllamaService instance)
get_qdrant_service     → VectorRepository (QdrantService, stored on app.state)
get_retrieval_engine   → RetrievalEngine (constructed per-request from app.state deps)
get_synthesizer        → ResponseSynthesizer (constructed per-request; wires
                          ContextBuilder with the model-specific token budget)
get_session_store      → SessionStore (singleton on app.state)
get_security_guard     → SecurityGuard (per-request; holds request_id for audit logs)
chat_rate_limit        → Dependency; raises RateLimitError when exceeded
ingest_rate_limit      → Dependency; raises RateLimitError when exceeded
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request

from app.config.settings import Settings, settings as _settings
from app.exceptions import RateLimitError
from app.services.llm.base import EmbeddingProvider, LLMProvider
from app.services.retrieval.engine import RetrievalEngine
from app.services.retrieval.keyword_index import KeywordIndex
from app.services.security.audit_logger import log_rate_limit_exceeded
from app.services.security.guard import SecurityGuard
from app.services.session.store import SessionStore
from app.services.synthesis.context_builder import ContextBuilder
from app.services.synthesis.prompt_config import get_prompt_config
from app.services.synthesis.synthesizer import ResponseSynthesizer
from app.services.vector.repository import VectorRepository


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return _settings


async def get_llm_provider(request: Request) -> LLMProvider:
    return request.app.state.llm_provider


async def get_embedding_provider(request: Request) -> EmbeddingProvider:
    return request.app.state.embedding_provider


async def get_qdrant_service(request: Request) -> VectorRepository:
    return request.app.state.qdrant_service


async def get_retrieval_engine(request: Request) -> RetrievalEngine:
    keyword_index: KeywordIndex | None = getattr(request.app.state, "keyword_index", None)
    return RetrievalEngine(
        embedding_provider=request.app.state.embedding_provider,
        qdrant=request.app.state.qdrant_service,
        keyword_index=keyword_index,
        default_top_k=_settings.retrieval_top_k,
        default_score_threshold=_settings.retrieval_score_threshold,
        default_max_chunks_per_note=_settings.retrieval_max_chunks_per_note,
        default_over_fetch_factor=_settings.retrieval_over_fetch_factor,
    )


async def get_synthesizer(request: Request) -> ResponseSynthesizer:
    config = get_prompt_config(_settings.ollama_chat_model)
    context_builder = ContextBuilder(max_context_tokens=config.context_budget)
    return ResponseSynthesizer(
        llm=request.app.state.llamaindex_llm,
        mode=_settings.synthesis_mode,
        context_builder=context_builder,
    )


async def get_session_store(request: Request) -> SessionStore:
    return request.app.state.session_store


async def get_security_guard(request: Request) -> SecurityGuard:
    """Per-request SecurityGuard, initialised with the request's trace ID."""
    request_id = getattr(request.state, "request_id", None)
    return SecurityGuard(request_id=request_id)


# ── Rate-limit dependencies ───────────────────────────────────────────────────

def _client_ip(request: Request) -> str:
    """Extract client IP, honouring X-Forwarded-For from reverse proxies.

    X-Forwarded-For may contain a comma-separated chain; the first entry is
    the original client.  Fall back to request.client.host (direct connection).
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def chat_rate_limit(request: Request) -> None:
    """FastAPI dependency — enforces the chat rate limit (30 req/min, burst 10).

    Raises RateLimitError (→ HTTP 429) when the bucket is exhausted.
    """
    limiter = request.app.state.chat_rate_limiter
    ip = _client_ip(request)
    if not limiter.check(ip):
        request_id = getattr(request.state, "request_id", None)
        log_rate_limit_exceeded(client_ip=ip, endpoint="chat", request_id=request_id)
        raise RateLimitError("chat")


async def ingest_rate_limit(request: Request) -> None:
    """FastAPI dependency — enforces the ingest rate limit (5 req/min, burst 2).

    Raises RateLimitError (→ HTTP 429) when the bucket is exhausted.
    """
    limiter = request.app.state.ingest_rate_limiter
    ip = _client_ip(request)
    if not limiter.check(ip):
        request_id = getattr(request.state, "request_id", None)
        log_rate_limit_exceeded(client_ip=ip, endpoint="ingest", request_id=request_id)
        raise RateLimitError("ingest")


# ── Type aliases ──────────────────────────────────────────────────────────────

SettingsDep = Annotated[Settings, Depends(get_settings)]
LLMDep = Annotated[LLMProvider, Depends(get_llm_provider)]
EmbedDep = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]
QdrantDep = Annotated[VectorRepository, Depends(get_qdrant_service)]
RetrievalDep = Annotated[RetrievalEngine, Depends(get_retrieval_engine)]
SynthesisDep = Annotated[ResponseSynthesizer, Depends(get_synthesizer)]
SessionDep = Annotated[SessionStore, Depends(get_session_store)]
SecurityGuardDep = Annotated[SecurityGuard, Depends(get_security_guard)]
ChatRateLimitDep = Annotated[None, Depends(chat_rate_limit)]
IngestRateLimitDep = Annotated[None, Depends(ingest_rate_limit)]
