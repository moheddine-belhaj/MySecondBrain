# Task 20 — Production Readiness

## Goal

Harden the project for reliable, observable, production-quality deployment without adding unnecessary complexity. A personal RAG system running on a single host does not need Kubernetes or Prometheus. The goal is: clear errors, fast diagnosis, safe restarts, and a one-command backup.

---

## Files Changed

| File | Action | What changed |
|---|---|---|
| `backend/app/startup.py` | New | Pre-flight validator: vault path, writable data dir, Qdrant reachability, Ollama reachability |
| `backend/app/main.py` | Modified | Call `validate_startup()` before building services; log boot time; log shutdown start/end |
| `backend/app/api/system.py` | Modified | Added `/readiness` probe; `/status` now includes `keyword_index_size` |
| `backend/app/middleware.py` | Modified | Added slow-request warning (>5 s gets a WARNING log instead of INFO) |
| `docker/Dockerfile.backend` | Modified | Added `tini` for PID 1 signal handling; added `HEALTHCHECK`; created `/app/data` directory |
| `docker/docker-compose.prod.yml` | Modified | Resource limits for all services; `backend_data` volume for index state persistence; `ENVIRONMENT=production` |
| `scripts/backup.sh` | New | Qdrant snapshot API + vault tar.gz + index state copy |
| `docs/architecture.md` | Updated | Replaced outdated module map; added full request flow diagrams; explained all design decisions |

---

## What Was Added

### 1. Startup Validation (`app/startup.py`)

Before any service object is built, four checks run concurrently:

```
validate_startup()
  ├─ _check_vault_path()     — vault exists, is a directory, is readable
  ├─ _check_state_path()     — data/ parent exists and is writable (creates it if not)
  ├─ _check_qdrant()         — GET /healthz returns 200 within 5 s
  └─ _check_ollama()         — GET /api/tags returns 200; warns if configured models missing
```

On failure, a `StartupError` is raised with an **actionable message** (`Fix: ...`). The lifespan handler catches it and exits with code 1 before uvicorn accepts any traffic. Without this, failures produce cryptic tracebacks mid-request.

**Example output when Qdrant is down:**
```
CRITICAL app.startup: Startup validation failed — aborting
  reason: Cannot connect to Qdrant at http://localhost:6333/healthz
  Fix: start Qdrant (docker compose up qdrant) and check QDRANT_HOST / QDRANT_PORT.
```

---

### 2. Boot and Shutdown Timing (`main.py`)

```python
t_boot = time.monotonic()
# ... all setup ...
logger.info("Ready", extra={"boot_ms": boot_ms, "env": settings.environment})
# yield — serving traffic
logger.info("Shutdown complete", extra={"shutdown_ms": shutdown_ms})
```

Boot time appears in every deploy log. Sudden increases (e.g. Qdrant rebuild taking 10 s instead of 200 ms) signal index growth worth monitoring.

---

### 3. Liveness vs Readiness Probes (`api/system.py`)

| Endpoint | Semantic | When to use |
|---|---|---|
| `GET /health` | Liveness — is the process alive? | Docker `HEALTHCHECK`, Kubernetes `livenessProbe` |
| `GET /readiness` | Readiness — can it serve traffic? | Load balancer health check, Kubernetes `readinessProbe` |
| `GET /status` | Full diagnostic — all component details | Dashboards, manual debugging |

**Why separate them?**

If `/readiness` and `/health` are the same endpoint and Qdrant goes down, a container orchestrator sees a "failed health check" and restarts the container — even though the Python process is perfectly healthy. The restart doesn't fix Qdrant and creates a restart loop. Separating them means:
- Container stays alive (`/health` = ok)
- Container is removed from rotation (`/readiness` = 503)
- When Qdrant recovers, `/readiness` returns 200 and traffic resumes — no restart needed

`/status` now also includes `keyword_index_size` so you can verify BM25 corpus is loaded without reading logs.

---

### 4. Slow Request Warning (`middleware.py`)

```python
_SLOW_REQUEST_MS = 5_000  # 5 seconds

if duration_ms > _SLOW_REQUEST_MS:
    logger.warning("Slow request", extra={...})
else:
    logger.info("Request", extra={...})
```

Any request taking longer than 5 s emits a `WARNING` log. Log aggregators (e.g. Grafana Loki, Papertrail) can alert on `level=WARNING path=/api/v1/chat` without any Prometheus setup.

---

### 5. Docker — tini + HEALTHCHECK (`Dockerfile.backend`)

**tini** is a minimal init process that:
- Forwards signals (SIGTERM, SIGINT) to the child process — uvicorn receives `docker stop`
- Reaps zombie processes (Python threads don't always clean up)
- Allows graceful shutdown within the configured timeout

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD wget -qO- http://localhost:8000/health || exit 1
```

Baking the `HEALTHCHECK` into the image means it works even without a compose file (e.g. `docker run`).

**`--timeout-graceful-shutdown 30`** added to the prod `CMD`: uvicorn waits up to 30 s for in-flight requests to complete before forcing a close.

---

### 6. Resource Limits (`docker-compose.prod.yml`)

```yaml
backend:
  deploy:
    resources:
      limits:
        memory: 512m
      reservations:
        memory: 128m
```

| Service | Memory limit | Rationale |
|---|---|---|
| Qdrant | 1 GB | Vector index for 50k chunks fits easily; limit prevents OOM kill of host |
| Ollama | 8 GB | Model weights live here; `llama3.2:3b` ≈ 2.4 GB, larger models need more |
| Backend | 512 MB | FastAPI + BM25 in-process index; a 50k-chunk corpus ≈ 50–100 MB RAM |
| Frontend | 256 MB | Nuxt SSR; Node process with no hot reload overhead |

`restart: always` (not `unless-stopped`) in prod means services restart even after a manual `docker stop`, which is almost never what you want in dev but correct for unattended production.

---

### 7. Index State Persistence (`docker-compose.prod.yml`)

```yaml
volumes:
  backend_data:   # persists data/index_state.json across container restarts

backend:
  volumes:
    - backend_data:/app/data
```

Without this, container restarts lose the sync state and the next `POST /ingest/sync` treats every note as new (full re-index). The `backend_data` named volume persists across `docker compose down` and image rebuilds.

---

### 8. Backup Strategy (`scripts/backup.sh`)

```bash
./scripts/backup.sh
# → backup/20260714_143022/
#     qdrant_second_brain.snapshot   ← Qdrant binary snapshot
#     vault.tar.gz                   ← all .md files
#     index_state.json               ← note hash state
```

**Qdrant snapshot** uses the native snapshot API (`POST /collections/{name}/snapshots`). This is a consistent, atomic point-in-time snapshot — not a file-level copy of `/qdrant/storage`. Restoring is a single API call.

**Restore command** is printed at the end of the script so you don't have to look it up under pressure.

**Scheduling (cron example):**
```cron
0 3 * * * cd /opt/second-brain && ./scripts/backup.sh >> /var/log/second-brain-backup.log 2>&1
```

**Retention (simple):**
```bash
# Keep last 7 days of backups
find ./backup -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +
```

---

## Production Concerns

### Secrets management

`.env` files are fine for development and single-user home servers. For a shared host or cloud deployment:
- Do not commit `.env` to git (already in `.gitignore`)
- For Docker Swarm: use Docker secrets
- For Kubernetes: use Kubernetes Secrets (or Vault)
- For a simple VPS: use a secrets manager like `pass` or `gopass` to inject env vars at deploy time

### TLS termination

The FastAPI container runs plain HTTP on port 8000. In production:
- Put a reverse proxy in front (Caddy is the simplest — automatic HTTPS via Let's Encrypt)
- Never expose port 8000 to the public internet directly

**Caddy example (`Caddyfile`):**
```
secondbrain.yourdomain.com {
    reverse_proxy localhost:8000
}
```

### Data durability

Qdrant data is in a Docker named volume (`qdrant_data`). This survives container restarts but NOT:
- `docker volume rm qdrant_data`
- Host disk failure

Run `./scripts/backup.sh` on a schedule and store backups off-host (S3, rsync to a second machine).

### Scaling limits

This architecture is deliberately single-host. The limits are:
- **Qdrant**: scales to millions of vectors on a single node with enough RAM
- **Ollama**: single GPU/CPU; generation is the bottleneck
- **BM25 index**: held in RAM; 50k chunks ≈ 50–150 MB
- **Session store**: in-memory; sessions are lost on container restart (by design for a personal app)

For multi-user or multi-host needs, the natural next steps are:
1. Move session store to Redis
2. Move Ollama behind a load balancer with multiple replicas
3. Use Qdrant's distributed mode (cluster of 3+ nodes)

---

## Deployment Checklist

```
☐ Copy .env.example → .env and fill in all values
☐ Set ENVIRONMENT=production
☐ Set ALLOWED_ORIGINS to your actual domain(s)
☐ Verify vault is mounted at VAULT_PATH
☐ Run docker compose build
☐ Run docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
☐ Check GET /health → {"status":"ok"}
☐ Check GET /readiness → {"status":"ok"}  (fails if Qdrant/Ollama not ready)
☐ Check GET /status → all components "ok", keyword_index_size > 0
☐ POST /api/v1/ingest to index your vault
☐ Test GET /api/v1/search?q=something
☐ Set up cron for ./scripts/backup.sh
```

---

## How to Test

See the section below — all changes are testable with the existing test suite plus a few manual checks.
