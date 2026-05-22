"""FastAPI dependency providers.

Pattern: endpoints declare `Depends(get_X)` — they never construct resources.
This allows tests to swap any provider without touching endpoint code.

Current providers
-----------------
get_settings           → Settings singleton
get_llm_provider       → LLMProvider (currently OllamaService, stored on app.state)
get_embedding_provider → EmbeddingProvider (same OllamaService instance)
get_qdrant_service     → QdrantService (stored on app.state)
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request

from app.config.settings import Settings, settings as _settings
from app.services.llm.base import EmbeddingProvider, LLMProvider
from app.services.vector.client import QdrantService


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


async def get_qdrant_service(request: Request) -> QdrantService:
    return request.app.state.qdrant_service


# ── Type aliases ──────────────────────────────────────────────────────────────

SettingsDep = Annotated[Settings, Depends(get_settings)]
LLMDep = Annotated[LLMProvider, Depends(get_llm_provider)]
EmbedDep = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]
QdrantDep = Annotated[QdrantService, Depends(get_qdrant_service)]
