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
get_synthesizer        → ResponseSynthesizer (constructed per-request from app.state LLM)
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request

from app.config.settings import Settings, settings as _settings
from app.services.llm.base import EmbeddingProvider, LLMProvider
from app.services.retrieval.engine import RetrievalEngine
from app.services.synthesis.synthesizer import ResponseSynthesizer
from app.services.vector.repository import VectorRepository


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return _settings


async def get_llm_provider(request: Request) -> LLMProvider:
    """Return the LLM provider wired during lifespan startup.

    Reading from request.app.state (not a module global) means tests can
    mount a TestClient with a different app.state and get a clean override
    without any global state mutation.
    """
    return request.app.state.llm_provider


async def get_embedding_provider(request: Request) -> EmbeddingProvider:
    return request.app.state.embedding_provider


async def get_qdrant_service(request: Request) -> VectorRepository:
    return request.app.state.qdrant_service


async def get_retrieval_engine(request: Request) -> RetrievalEngine:
    """Construct a RetrievalEngine from the shared app.state providers.

    RetrievalEngine is stateless between calls, so constructing it per-request
    is cheap. It holds references to the shared, connection-pooled providers
    (embedding_provider and qdrant_service) — no new connections are opened.
    """
    return RetrievalEngine(
        embedding_provider=request.app.state.embedding_provider,
        qdrant=request.app.state.qdrant_service,
        default_top_k=_settings.retrieval_top_k,
        default_score_threshold=_settings.retrieval_score_threshold,
        default_max_chunks_per_note=_settings.retrieval_max_chunks_per_note,
        default_over_fetch_factor=_settings.retrieval_over_fetch_factor,
    )


async def get_synthesizer(request: Request) -> ResponseSynthesizer:
    """Construct a ResponseSynthesizer from the shared LlamaIndex LLM on app.state.

    Stateless between calls — cheap to construct per-request. The LlamaIndex
    Ollama LLM (`app.state.llamaindex_llm`) holds the actual HTTP client and
    is created once in lifespan.
    """
    return ResponseSynthesizer(
        llm=request.app.state.llamaindex_llm,
        mode=_settings.synthesis_mode,
    )


# ── Type aliases ──────────────────────────────────────────────────────────────

SettingsDep = Annotated[Settings, Depends(get_settings)]
LLMDep = Annotated[LLMProvider, Depends(get_llm_provider)]
EmbedDep = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]
QdrantDep = Annotated[VectorRepository, Depends(get_qdrant_service)]
RetrievalDep = Annotated[RetrievalEngine, Depends(get_retrieval_engine)]
SynthesisDep = Annotated[ResponseSynthesizer, Depends(get_synthesizer)]
