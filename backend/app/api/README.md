# api

HTTP layer. Endpoints stay thin: validate, call services via dependencies, shape the response.

- `system.py`: unversioned operational endpoints (mounted at the root).
- `v1/`: versioned API under `API_PREFIX` (`/api/v1`). See [v1/README.md](v1/README.md).

## System endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness: process is up. Does not check dependencies |
| GET | `/readiness` | Readiness: 200 if Qdrant and Ollama are reachable, else 503 |
| GET | `/status` | Full status of Qdrant, Ollama and the app |
| GET | `/models` | Models downloaded in Ollama plus the configured chat/embed models |
