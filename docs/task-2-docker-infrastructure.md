# Task 2 — Docker Infrastructure Setup

## Goal

Replace the Task 1 Docker stubs with a complete, production-expandable local
development infrastructure. Every service must start in the correct order, be
reachable by the others using DNS-based service names, and support hot-reload
without a container rebuild.

---

## Problem with the Task 1 Stubs

The initial `docker-compose.yml` had four critical flaws:

| Problem | Effect |
|---|---|
| Services used `localhost` host names in `.env.example` | Backend could not reach Qdrant or Ollama inside Docker |
| No `healthcheck` | `depends_on` triggered immediately; backend started before Qdrant was ready |
| No explicit network | Docker's default bridge does not guarantee service-name DNS resolution |
| No dev vs prod separation | Hot-reload and production images have incompatible requirements |

All four are fixed in Task 2.

---

## Files Created / Modified

```
docker/
├── docker-compose.yml          ← full rewrite
├── docker-compose.prod.yml     ← new: production overrides
├── Dockerfile.backend          ← full rewrite (multi-stage)
├── Dockerfile.frontend         ← full rewrite (multi-stage + CVE fix)
└── .dockerignore               ← unchanged
```

---

## `docker-compose.yml` — Annotated

### Network

```yaml
networks:
  second-brain-net:
    driver: bridge
```

A single named bridge network. Every service is attached to it, so they can
address each other by service name (`qdrant`, `ollama`, `backend`, `frontend`).
Without a named network, Docker's default bridge assigns container IDs as
hostnames, which are not stable and differ per run.

---

### Volumes

```yaml
volumes:
  qdrant_data:   # persists embeddings across restarts
  ollama_data:   # persists downloaded model weights
```

Named volumes survive `docker compose down` and `docker compose up`. This means:
- Qdrant does not lose the vector index when the container restarts.
- Ollama does not re-download multi-GB models on every start.

To wipe state intentionally: `docker volume rm second-brain_qdrant_data`.

---

### Service: `qdrant`

```yaml
qdrant:
  image: qdrant/qdrant:v1.12.4
  networks: [second-brain-net]
  ports:
    - "6333:6333"   # REST API + web UI → http://localhost:6333/dashboard
    - "6334:6334"   # gRPC (unused in dev, available for prod tuning)
  volumes:
    - qdrant_data:/qdrant/storage
  healthcheck:
    test: ["CMD-SHELL", "wget -qO- http://localhost:6333/healthz || exit 1"]
    interval: 10s
    timeout: 5s
    retries: 5
    start_period: 10s
```

**Why `wget` not `curl`?** Qdrant's image is Debian-based and ships `wget` but
not always `curl`. Using `wget` avoids a missing-binary error.

**Why pin the image tag?** `qdrant/qdrant:latest` can receive breaking schema
changes. The pinned tag `v1.12.4` ensures the environment is reproducible.

---

### Service: `ollama`

```yaml
ollama:
  image: ollama/ollama:0.5.1
  networks: [second-brain-net]
  ports:
    - "11434:11434"   # Ollama REST API
  volumes:
    - ollama_data:/root/.ollama
  healthcheck:
    test: ["CMD", "ollama", "list"]
    interval: 10s
    timeout: 10s
    retries: 10
    start_period: 20s
```

**Why `ollama list` for healthcheck?** Ollama's image does not ship `curl` or
`wget`. The `ollama` binary itself is always present and exits 0 only when the
local server is responsive.

**Why `start_period: 20s`?** Ollama initialises its model registry on first
start, which can take 10–15 seconds before it accepts connections. Without a
start period, Docker retries immediately and marks the service unhealthy before
it finishes booting.

**GPU passthrough** (commented out):
```yaml
# deploy:
#   resources:
#     reservations:
#       devices:
#         - driver: nvidia
#           count: 1
#           capabilities: [gpu]
```
Uncomment this block if the host has an NVIDIA GPU and the NVIDIA Container
Toolkit installed. CPU-only runs fine for `llama3.2` at small context sizes.

---

### Service: `ollama-init`

```yaml
ollama-init:
  image: ollama/ollama:0.5.1
  environment:
    OLLAMA_HOST: http://ollama:11434
  entrypoint: ["/bin/sh", "-c"]
  command:
    - |
      ollama pull nomic-embed-text
      ollama pull llama3.2
  depends_on:
    ollama:
      condition: service_healthy
  restart: "no"
```

A one-shot init container that pulls the two required models into the shared
`ollama_data` volume. Key design points:

| Point | Decision |
|---|---|
| `restart: "no"` | Exits after pulling; does not loop forever |
| `condition: service_healthy` | Waits for Ollama's HTTP server before pulling |
| Does NOT block backend | Backend depends on `ollama` (healthy server), not on `ollama-init` |
| Re-runs are fast | `ollama pull` is a no-op if the model is already in the volume |

The backend starts as soon as Ollama's server is ready, even if models are still
downloading. This is intentional — the backend can accept health checks and
non-AI requests while models load in the background.

---

### Service: `backend`

```yaml
backend:
  build:
    context: ../backend
    dockerfile: ../docker/Dockerfile.backend
    target: dev
  ports:
    - "8000:8000"
  volumes:
    - ../backend/app:/app/app    # bind mount for hot reload
    - ../vault:/app/vault:ro    # read-only vault
  environment:
    DEBUG: "true"
    QDRANT_HOST: qdrant          # service name, NOT localhost
    OLLAMA_BASE_URL: http://ollama:11434
  env_file:
    - ../backend/.env
  depends_on:
    qdrant:
      condition: service_healthy
    ollama:
      condition: service_healthy
```

**The hostname problem (and fix):**
`backend/.env.example` uses `QDRANT_HOST=localhost` for running uvicorn directly
on the host machine. Inside Docker, `localhost` refers to the container itself,
not to the Qdrant container. The `environment:` block in Compose overrides the
`.env` value with the Docker service name `qdrant`. `environment:` always wins
over `env_file:` for the same key.

**Hot reload:**
Only `app/` is bind-mounted. The installed Python packages (in the container's
site-packages) come from the image build. This avoids the common pitfall of
mounting the entire backend directory and losing installed deps.

---

### Service: `frontend`

```yaml
frontend:
  build:
    context: ../frontend
    dockerfile: ../docker/Dockerfile.frontend
    target: dev
  ports:
    - "3000:3000"    # Nuxt dev server
    - "24678:24678"  # Vite HMR WebSocket
  volumes:
    - ../frontend:/app          # bind mount for hot reload
    - /app/node_modules         # anonymous volume — keeps container's packages
    - /app/.nuxt                # anonymous volume — keeps Nuxt build cache
  environment:
    NUXT_PUBLIC_API_BASE: http://localhost:8000/api/v1
    CHOKIDAR_USEPOLLING: "true"
```

**Why `NUXT_PUBLIC_API_BASE` uses `localhost:8000` not `backend:8000`?**
`NUXT_PUBLIC_` values are embedded into the browser bundle at build time. The
browser runs on the user's machine, not inside Docker. From the browser's
perspective, the backend is at `localhost:8000` (because port 8000 is forwarded
from Docker to the host). The frontend container can reach the backend at
`http://backend:8000`, but that address does not work in the browser.

**Why anonymous volumes for `node_modules` and `.nuxt`?**
If only `../frontend:/app` is mounted, the host's `node_modules` (or absence of
it) shadows the container's installed packages. The anonymous volumes prevent the
host from overwriting those directories, keeping the container's deps isolated.

**`CHOKIDAR_USEPOLLING=true`:** On Linux with bind mounts, `inotify` events do
not always propagate from the host into the container. Polling guarantees Vite
sees file changes.

---

## `docker-compose.prod.yml` — Production Overrides

```yaml
services:
  backend:
    build:
      target: prod          # no --reload, 2 uvicorn workers
    volumes:
      - ../vault:/app/vault:ro   # vault still needed; no source bind mount
    environment:
      DEBUG: "false"

  frontend:
    build:
      target: prod          # compiled .output, not dev server
    volumes: []             # no bind mounts
    environment:
      NODE_ENV: production
```

Usage:
```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  up -d
```

The prod file only overrides what differs. All shared config (networks, volumes,
healthchecks, Qdrant, Ollama) stays in the base file.

---

## `Dockerfile.backend` — Multi-Stage

```dockerfile
# ── base ──────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS base
WORKDIR /app

RUN pip install --no-cache-dir uv==0.5.14

COPY requirements/base.txt requirements/base.txt
RUN uv pip install --system --no-cache -r requirements/base.txt

RUN useradd -m -u 1001 appuser
COPY --chown=appuser:appuser . .

# ── dev ───────────────────────────────────────────────────────────────────────
FROM base AS dev
USER appuser
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ── prod ──────────────────────────────────────────────────────────────────────
FROM base AS prod
USER appuser
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

| Decision | Reason |
|---|---|
| `python:3.12-slim` not `python:3.12` | Full image adds ~800 MB of unused tooling |
| `uv` for pip install | 10–100× faster than pip; deterministic output |
| `useradd -m -u 1001 appuser` | Non-root user — if an RCE exists, the attacker has no write access outside `/app` |
| `requirements/base.txt` copied before `COPY . .` | Keeps the dependency layer cached when only source files change |
| `--workers 2` in prod | Safe default for a single-core I/O-bound process; raise with `WEB_CONCURRENCY` |

---

## `Dockerfile.frontend` — Multi-Stage + CVE Fix

```dockerfile
# Alpine version pinned (not floating :alpine tag)
# apk upgrade patches any CVEs that landed after the image was published

FROM node:22-alpine3.21 AS dev
RUN apk upgrade --no-cache
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
EXPOSE 3000 24678
CMD ["npm", "run", "dev"]

FROM node:22-alpine3.21 AS builder
RUN apk upgrade --no-cache
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-alpine3.21 AS prod
RUN apk upgrade --no-cache
WORKDIR /app
COPY --from=builder /app/.output ./.output
ENV NODE_ENV=production
EXPOSE 3000
CMD ["node", ".output/server/index.mjs"]
```

**CVE fix applied:** The IDE scanner flagged a high vulnerability in
`node:22-alpine` (the floating tag). Two changes were made:

1. **`node:22-alpine` → `node:22-alpine3.21`** — Floating tags move whenever
   Alpine cuts a new release. Pinning to `alpine3.21` makes the base immutable
   so the scanner tracks CVEs against a known surface.

2. **`RUN apk upgrade --no-cache`** — Applies any in-repository Alpine security
   patches that landed after the Docker Hub image was published. This is the
   standard Alpine hardening pattern for pinned tags.

**Prod stage is minimal:** Only the compiled `.output` is copied from the builder
stage. No `node_modules`, no source files, no dev dependencies.

---

## Port Map

| Port | Service | Purpose |
|---|---|---|
| `3000` | frontend | Nuxt dev server / production SSR |
| `8000` | backend | FastAPI HTTP API |
| `6333` | qdrant | REST API + web dashboard (`/dashboard`) |
| `6334` | qdrant | gRPC (unused in dev) |
| `11434` | ollama | Ollama REST API |
| `24678` | frontend | Vite HMR WebSocket (dev only) |

---

## Volume Map

| Volume | Mount point | What it stores |
|---|---|---|
| `qdrant_data` | `/qdrant/storage` | Vector embeddings, Qdrant collections |
| `ollama_data` | `/root/.ollama` | Downloaded model weights (GB-sized) |
| `../backend/app` | `/app/app` | Backend source (hot reload, dev only) |
| `../vault` | `/app/vault` (ro) | Obsidian markdown notes |
| `../frontend` | `/app` | Frontend source (hot reload, dev only) |
| anonymous | `/app/node_modules` | Isolates container packages from host |
| anonymous | `/app/.nuxt` | Preserves Nuxt build cache across restarts |

---

## Quick Start

```bash
cd docker

# Start all services (first run pulls models — may take several minutes)
docker compose up

# Start only infrastructure (run backend and frontend locally)
docker compose up qdrant ollama -d

# Start in production mode
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Check service health
docker compose ps

# Wipe vector index (re-ingest required after this)
docker volume rm second-brain_qdrant_data

# Wipe Ollama models (models will be re-downloaded on next up)
docker volume rm second-brain_ollama_data
```

---

## What This Task Enables

- All four services start in dependency order with readiness guarantees.
- Backend reaches Qdrant at `http://qdrant:6333` and Ollama at
  `http://ollama:11434` using Docker DNS.
- Code changes in `backend/app/` and `frontend/` are picked up without
  rebuilding the image.
- Ollama models are pulled automatically on first start.
- A single compose override file switches the entire stack to production mode.

## What Is NOT Done Here

- The backend does not yet use Qdrant or Ollama — those connections are wired
  in Tasks 3 and 4.
- No reverse proxy (nginx/Caddy) for production TLS — out of scope for local dev.
- No CI pipeline — added later.
