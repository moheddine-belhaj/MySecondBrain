"""Startup validation — runs once during lifespan before traffic is accepted.

Checks that every hard dependency is reachable and every required path is
accessible. Failures raise StartupError so the process exits immediately with
a clear, actionable message instead of a cryptic traceback mid-request.

Design:
  - Probe Qdrant and Ollama with a short timeout (5 s).
  - Check vault path exists and is readable.
  - Check index state path parent directory is writable.
  - Warn (not error) if configured models are not yet downloaded.

Call order in main.py lifespan:
  1. setup_logging()
  2. await validate_startup()   ← this module
  3. build service objects
  4. yield
"""

import logging
import os
from pathlib import Path

import httpx

from app.config.settings import settings

logger = logging.getLogger("app.startup")

_PROBE_TIMEOUT = 5.0  # seconds — generous enough for a slow cold start


class StartupError(RuntimeError):
    """Raised when a required dependency or path check fails at startup."""


# ── Individual checks ──────────────────────────────────────────────────────────

def _check_vault_path() -> None:
    vault = Path(settings.vault_path).resolve()
    if not vault.exists():
        raise StartupError(
            f"Vault path does not exist: {vault}\n"
            f"  Fix: create the directory or set VAULT_PATH to an existing path."
        )
    if not vault.is_dir():
        raise StartupError(
            f"Vault path is not a directory: {vault}\n"
            f"  Fix: VAULT_PATH must point to a directory, not a file."
        )
    if not os.access(vault, os.R_OK):
        raise StartupError(
            f"Vault path is not readable: {vault}\n"
            f"  Fix: check file permissions or container volume mount."
        )
    logger.info("Startup: vault path OK", extra={"vault": str(vault)})


def _check_state_path() -> None:
    state = Path(settings.index_state_path).resolve()
    parent = state.parent
    if not parent.exists():
        try:
            parent.mkdir(parents=True, exist_ok=True)
            logger.info("Startup: created index state directory", extra={"path": str(parent)})
        except OSError as exc:
            raise StartupError(
                f"Cannot create index state directory: {parent}\n"
                f"  Error: {exc}\n"
                f"  Fix: ensure the data directory is writable or set INDEX_STATE_PATH."
            ) from exc
    if not os.access(parent, os.W_OK):
        raise StartupError(
            f"Index state directory is not writable: {parent}\n"
            f"  Fix: check permissions or mount a writable volume."
        )
    logger.info("Startup: index state path OK", extra={"path": str(state)})


async def _check_qdrant() -> None:
    url = f"{settings.qdrant_url}/healthz"
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            r = await client.get(url)
        if r.status_code != 200:
            raise StartupError(
                f"Qdrant health check returned HTTP {r.status_code} at {url}\n"
                f"  Fix: ensure Qdrant is running and reachable."
            )
        logger.info("Startup: Qdrant OK", extra={"url": url})
    except httpx.ConnectError as exc:
        raise StartupError(
            f"Cannot connect to Qdrant at {url}\n"
            f"  Error: {exc}\n"
            f"  Fix: start Qdrant (docker compose up qdrant) and check QDRANT_HOST / QDRANT_PORT."
        ) from exc
    except httpx.TimeoutException as exc:
        raise StartupError(
            f"Qdrant probe timed out after {_PROBE_TIMEOUT}s at {url}\n"
            f"  Fix: check if Qdrant is overloaded or increase the probe timeout."
        ) from exc


async def _check_ollama() -> None:
    url = f"{settings.ollama_base_url}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            r = await client.get(url)
        if r.status_code != 200:
            raise StartupError(
                f"Ollama health check returned HTTP {r.status_code} at {url}\n"
                f"  Fix: ensure Ollama is running and reachable."
            )

        # Warn if configured models are not yet downloaded.
        data = r.json()
        available_names = {m["name"] for m in data.get("models", [])}
        for model in (settings.ollama_embed_model, settings.ollama_chat_model):
            # Ollama tags include version suffixes — check for prefix match.
            if not any(n == model or n.startswith(f"{model}:") for n in available_names):
                logger.warning(
                    "Startup: model not found in Ollama — first request will be slow",
                    extra={"model": model, "available": sorted(available_names)},
                )

        logger.info("Startup: Ollama OK", extra={"url": url})
    except httpx.ConnectError as exc:
        raise StartupError(
            f"Cannot connect to Ollama at {url}\n"
            f"  Error: {exc}\n"
            f"  Fix: start Ollama (docker compose up ollama) and check OLLAMA_BASE_URL."
        ) from exc
    except httpx.TimeoutException as exc:
        raise StartupError(
            f"Ollama probe timed out after {_PROBE_TIMEOUT}s at {url}\n"
            f"  Fix: check if Ollama is overloaded or the URL is correct."
        ) from exc


# ── Public entry point ─────────────────────────────────────────────────────────

async def validate_startup() -> None:
    """Run all startup checks. Raises StartupError on first failure.

    Called from main.py lifespan before any service objects are built.
    """
    logger.info("Startup: running pre-flight checks")

    # Synchronous path checks — fast, no I/O
    _check_vault_path()
    _check_state_path()

    # Async network probes — run concurrently
    import asyncio
    await asyncio.gather(
        _check_qdrant(),
        _check_ollama(),
    )

    logger.info("Startup: all checks passed")
