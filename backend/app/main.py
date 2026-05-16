import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.system import router as system_router
from app.api.v1 import router as api_v1_router
from app.config.settings import settings
from app.exceptions import register_exception_handlers
from app.logging_config import setup_logging
from app.middleware import LoggingMiddleware, RequestIDMiddleware
from app.services.llm.ollama import OllamaService

logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging(log_level=settings.log_level, log_format=settings.log_format)
    logger.info(
        "Starting",
        extra={
            "app": settings.app_name,
            "version": settings.app_version,
            "env": settings.environment,
        },
    )

    # ── Ollama client ──────────────────────────────────────────────────────────
    # A single AsyncClient is shared for the lifetime of the process.
    # httpx manages a connection pool internally — we get connection reuse
    # without any extra pooling code.
    #
    # Two separate timeout objects:
    #   chat_timeout  — long read timeout because generation can be slow on CPU
    #   embed_timeout — short read timeout because embedding is fast
    #
    # The `async with` context manager closes the underlying connections cleanly
    # when the lifespan exits (i.e. on server shutdown).
    chat_timeout = httpx.Timeout(
        connect=settings.ollama_connect_timeout,
        read=settings.ollama_chat_timeout,
        write=10.0,
        pool=5.0,
    )
    embed_timeout = httpx.Timeout(
        connect=settings.ollama_connect_timeout,
        read=settings.ollama_embed_timeout,
        write=10.0,
        pool=5.0,
    )

    # One client per timeout profile — both share the same base_url
    async with (
        httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=chat_timeout) as chat_client,
        httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=embed_timeout) as embed_client,
    ):
        ollama = OllamaService(
            chat_client=chat_client,
            embed_client=embed_client,
            chat_model=settings.ollama_chat_model,
            embed_model=settings.ollama_embed_model,
            max_retries=settings.ollama_max_retries,
            retry_delay=settings.ollama_retry_delay,
        )

        # Store providers on app.state — dependencies read from here.
        # Endpoints depend on the abstract LLMProvider / EmbeddingProvider types,
        # not on OllamaService. Swap to a different backend by changing only this block.
        app.state.llm_provider = ollama
        app.state.embedding_provider = ollama

        logger.info(
            "Ollama service ready",
            extra={
                "chat_model": settings.ollama_chat_model,
                "embed_model": settings.ollama_embed_model,
                "base_url": settings.ollama_base_url,
            },
        )
        yield

    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Local-first AI Second Brain — RAG over your Obsidian vault.",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    _register_middleware(app)
    register_exception_handlers(app)
    _register_routers(app)

    return app


def _register_middleware(app: FastAPI) -> None:
    # Execution order on request:  CORS → RequestID → Logging → handler
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(LoggingMiddleware)


def _register_routers(app: FastAPI) -> None:
    app.include_router(system_router)
    app.include_router(api_v1_router, prefix=settings.api_prefix)


app = create_app()
