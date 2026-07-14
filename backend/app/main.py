import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from llama_index.llms.ollama import Ollama as LlamaIndexOllama
from qdrant_client import AsyncQdrantClient

from app.api.system import router as system_router
from app.api.v1 import router as api_v1_router
from app.config.settings import settings
from app.exceptions import register_exception_handlers
from app.logging_config import setup_logging
from app.middleware import LoggingMiddleware, RequestIDMiddleware
from app.services.indexing import IndexStateStore, IncrementalSyncEngine
from app.services.ingestion import MarkdownChunker
from app.services.llm.ollama import OllamaService
from app.services.retrieval.keyword_index import KeywordIndex
from app.services.security.rate_limiter import RateLimiter
from app.services.session.store import SessionStore
from app.services.vault.scanner import VaultScanner
from app.services.vector.client import QdrantService
from app.startup import StartupError, validate_startup

logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    t_boot = time.monotonic()
    setup_logging(log_level=settings.log_level, log_format=settings.log_format)
    logger.info(
        "Starting",
        extra={
            "app": settings.app_name,
            "version": settings.app_version,
            "env": settings.environment,
        },
    )

    # ── Pre-flight checks ──────────────────────────────────────────────────────
    try:
        await validate_startup()
    except StartupError as exc:
        logger.critical("Startup validation failed — aborting", extra={"reason": str(exc)})
        raise SystemExit(1) from exc

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

        # ── Rate limiters ─────────────────────────────────────────────────────
        # Chat: 30 req/min, burst 10 — prevents Ollama DoS while allowing UI bursts.
        # Ingest: 5 req/min, burst 2 — embedding is expensive; rate-limit tightly.
        app.state.chat_rate_limiter = RateLimiter(requests_per_minute=30, burst=10)
        app.state.ingest_rate_limiter = RateLimiter(requests_per_minute=5, burst=2)
        logger.info("Rate limiters ready", extra={"chat_rpm": 30, "ingest_rpm": 5})

        # ── Session store ──────────────────────────────────────────────────────
        # Single in-memory store shared across all requests.
        # Max 100 sessions, 20 messages/session, 1-hour TTL.
        app.state.session_store = SessionStore(
            max_sessions=100,
            max_history=20,
            ttl_seconds=3600.0,
        )
        logger.info("Session store ready", extra={"max_sessions": 100, "ttl_s": 3600})

        logger.info(
            "Ollama service ready",
            extra={
                "chat_model": settings.ollama_chat_model,
                "embed_model": settings.ollama_embed_model,
                "base_url": settings.ollama_base_url,
            },
        )

        # ── LlamaIndex LLM (synthesis only) ───────────────────────────────────
        # LlamaIndex's Ollama adapter manages its own HTTP session internally.
        # It is used exclusively by ResponseSynthesizer for context compaction
        # and answer generation. All other Ollama calls go through OllamaService.
        app.state.llamaindex_llm = LlamaIndexOllama(
            model=settings.ollama_chat_model,
            base_url=settings.ollama_base_url,
            request_timeout=settings.ollama_chat_timeout,
        )
        logger.info(
            "LlamaIndex Ollama LLM ready",
            extra={
                "model": settings.ollama_chat_model,
                "synthesis_mode": settings.synthesis_mode,
            },
        )

        # ── Qdrant client ──────────────────────────────────────────────────────
        # AsyncQdrantClient manages its own HTTP session internally.
        # We wrap it in QdrantService (our abstraction) and store it on app.state.
        qdrant_client = AsyncQdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
        )
        app.state.qdrant_service = QdrantService(
            client=qdrant_client,
            collection_name=settings.qdrant_collection,
            vector_size=settings.qdrant_vector_size,
        )
        logger.info(
            "Qdrant service ready",
            extra={
                "host": settings.qdrant_host,
                "port": settings.qdrant_port,
                "collection": settings.qdrant_collection,
            },
        )

        # ── Incremental sync engine ────────────────────────────────────────────
        vault_path = Path(settings.vault_path).resolve()
        state_store = IndexStateStore(Path(settings.index_state_path).resolve())
        app.state.sync_engine = IncrementalSyncEngine(
            scanner=VaultScanner(vault_path),
            chunker=MarkdownChunker(
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
            ),
            embedding_provider=ollama,
            qdrant=app.state.qdrant_service,
            state_store=state_store,
            batch_size=settings.embed_batch_size,
        )
        logger.info(
            "Sync engine ready",
            extra={
                "vault": str(vault_path),
                "state_file": str(state_store.path),
            },
        )

        # ── Keyword index (BM25) ──────────────────────────────────────────────
        keyword_index = KeywordIndex()
        app.state.keyword_index = keyword_index
        try:
            entries = await app.state.qdrant_service.scroll_all_chunks()
            await asyncio.to_thread(keyword_index.build, entries)
            logger.info(
                "Keyword index built at startup",
                extra={"corpus_size": keyword_index.corpus_size},
            )
        except Exception:
            logger.warning(
                "Keyword index not built at startup — collection may be empty. "
                "Will build on first hybrid/keyword search."
            )

        # ── Optional background scheduler ──────────────────────────────────────
        sync_task: asyncio.Task | None = None
        if settings.sync_interval_minutes > 0:
            sync_task = asyncio.create_task(
                _auto_sync_loop(app.state.sync_engine, settings.sync_interval_minutes * 60)
            )
            app.state.sync_task = sync_task
            logger.info(
                "Auto-sync scheduler started",
                extra={"interval_minutes": settings.sync_interval_minutes},
            )
        else:
            app.state.sync_task = None
            logger.info("Auto-sync scheduler disabled (sync_interval_minutes=0)")

        boot_ms = round((time.monotonic() - t_boot) * 1000)
        logger.info("Ready", extra={"boot_ms": boot_ms, "env": settings.environment})

        yield

        t_shutdown = time.monotonic()
        logger.info("Shutting down — draining in-flight requests")

        if sync_task is not None:
            sync_task.cancel()
            try:
                await sync_task
            except asyncio.CancelledError:
                pass

        await qdrant_client.close()
        shutdown_ms = round((time.monotonic() - t_shutdown) * 1000)

    logger.info("Shutdown complete", extra={"shutdown_ms": shutdown_ms})


async def _auto_sync_loop(engine: IncrementalSyncEngine, interval_seconds: int) -> None:
    """Background task: run incremental sync every `interval_seconds`."""
    logger = logging.getLogger("app.sync_scheduler")
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            stats = await engine.sync()
            logger.info(
                "Scheduled sync complete",
                extra={
                    "new": stats.new_notes,
                    "modified": stats.modified_notes,
                    "deleted": stats.deleted_notes,
                    "errors": len(stats.errors),
                },
            )
        except Exception:
            logger.exception("Scheduled sync failed")


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
