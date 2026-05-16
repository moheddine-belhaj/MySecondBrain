"""System-level endpoints — not versioned, not behind /api/v1.

These are consumed by infrastructure (Docker healthchecks, load balancers,
monitoring dashboards) rather than by application clients. They must:
  - Always respond quickly (timeout < 3 s per external check)
  - Never return 5xx when a downstream service is down — use a degraded status
    instead so the app process itself stays "healthy" in the eyes of the
    orchestrator even when Qdrant or Ollama are temporarily unreachable.
"""

import logging
import time
from enum import Enum

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from app.config.settings import settings

router = APIRouter(tags=["system"])
logger = logging.getLogger("app.health")

_PROBE_TIMEOUT = 3.0  # seconds per external service check


# ── Models ────────────────────────────────────────────────────────────────────

class ServiceStatus(str, Enum):
    ok = "ok"
    degraded = "degraded"
    unavailable = "unavailable"


class ComponentHealth(BaseModel):
    status: ServiceStatus
    latency_ms: float | None = None
    message: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str


class StatusResponse(BaseModel):
    status: ServiceStatus
    version: str
    environment: str
    components: dict[str, ComponentHealth]


class ModelInfo(BaseModel):
    name: str
    size: int | None = None
    digest: str | None = None


class ModelsResponse(BaseModel):
    chat_model: str
    embed_model: str
    available: list[ModelInfo]


# ── Internal probes ───────────────────────────────────────────────────────────

async def _probe_qdrant() -> ComponentHealth:
    url = f"{settings.qdrant_url}/healthz"
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            r = await client.get(url)
        latency = round((time.perf_counter() - start) * 1000, 2)
        if r.status_code == 200:
            return ComponentHealth(status=ServiceStatus.ok, latency_ms=latency)
        return ComponentHealth(
            status=ServiceStatus.degraded,
            latency_ms=latency,
            message=f"HTTP {r.status_code}",
        )
    except httpx.ConnectError:
        return ComponentHealth(status=ServiceStatus.unavailable, message="Connection refused")
    except httpx.TimeoutException:
        return ComponentHealth(status=ServiceStatus.unavailable, message="Timeout")
    except Exception as exc:
        logger.warning("Qdrant probe failed", extra={"error": str(exc)})
        return ComponentHealth(status=ServiceStatus.unavailable, message=str(exc))


async def _probe_ollama() -> ComponentHealth:
    url = f"{settings.ollama_base_url}/api/tags"
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            r = await client.get(url)
        latency = round((time.perf_counter() - start) * 1000, 2)
        if r.status_code == 200:
            return ComponentHealth(status=ServiceStatus.ok, latency_ms=latency)
        return ComponentHealth(
            status=ServiceStatus.degraded,
            latency_ms=latency,
            message=f"HTTP {r.status_code}",
        )
    except httpx.ConnectError:
        return ComponentHealth(status=ServiceStatus.unavailable, message="Connection refused")
    except httpx.TimeoutException:
        return ComponentHealth(status=ServiceStatus.unavailable, message="Timeout")
    except Exception as exc:
        logger.warning("Ollama probe failed", extra={"error": str(exc)})
        return ComponentHealth(status=ServiceStatus.unavailable, message=str(exc))


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness probe",
    description=(
        "Returns 200 as long as the Python process is alive. "
        "Used by Docker HEALTHCHECK and load balancers. "
        "Does NOT check downstream services."
    ),
)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version=settings.app_version)


@router.get(
    "/status",
    response_model=StatusResponse,
    summary="Full system status",
    description=(
        "Probes Qdrant and Ollama and returns their connectivity status. "
        "Always returns 200 — the top-level `status` field reflects the "
        "worst-case component: ok → degraded → unavailable."
    ),
)
async def status_check() -> StatusResponse:
    import asyncio

    qdrant_health, ollama_health = await asyncio.gather(
        _probe_qdrant(),
        _probe_ollama(),
    )

    components = {"qdrant": qdrant_health, "ollama": ollama_health}

    # Aggregate: worst component status bubbles up
    statuses = [c.status for c in components.values()]
    if any(s == ServiceStatus.unavailable for s in statuses):
        overall = ServiceStatus.unavailable
    elif any(s == ServiceStatus.degraded for s in statuses):
        overall = ServiceStatus.degraded
    else:
        overall = ServiceStatus.ok

    logger.info("Status check", extra={"overall": overall, "components": {
        k: v.status for k, v in components.items()
    }})

    return StatusResponse(
        status=overall,
        version=settings.app_version,
        environment=settings.environment,
        components=components,
    )


@router.get(
    "/models",
    response_model=ModelsResponse,
    summary="Available Ollama models",
    description="Returns the list of models currently downloaded in Ollama, plus the configured chat and embed model names.",
)
async def list_models() -> ModelsResponse:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{settings.ollama_base_url}/api/tags")
            r.raise_for_status()
            data = r.json()

        available = [
            ModelInfo(
                name=m["name"],
                size=m.get("size"),
                digest=m.get("digest"),
            )
            for m in data.get("models", [])
        ]
        return ModelsResponse(
            chat_model=settings.ollama_chat_model,
            embed_model=settings.ollama_embed_model,
            available=available,
        )
    except httpx.ConnectError:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Ollama is not reachable")
    except httpx.HTTPStatusError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=502, detail=f"Ollama returned {exc.response.status_code}")
    except Exception as exc:
        logger.exception("Failed to list models", exc_info=exc)
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Could not fetch models from Ollama")
