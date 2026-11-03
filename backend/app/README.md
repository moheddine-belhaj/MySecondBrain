# app

Application package. Entry point is `main.py`.

## Top-level modules
| File | Role |
|------|------|
| `main.py` | `create_app()`, lifespan (builds shared services on `app.state`, optional auto-sync loop), mounts routers and middleware |
| `startup.py` | `validate_startup()`: checks required paths/dependencies before serving; raises `StartupError` |
| `dependencies.py` | FastAPI dependency providers (LLM, embeddings, Qdrant, retrieval, synthesizer, sessions, per-request `SecurityGuard`, rate limits) |
| `exceptions.py` | `AppError` hierarchy and handlers; every error returns a JSON body with the request ID |
| `middleware.py` | `RequestIDMiddleware` (unique ID per request), `LoggingMiddleware` (method, path, status, duration) |
| `logging_config.py` | `setup_logging()`; JSON formatter for production, coloured console for dev |

## Errors
| Exception | HTTP |
|-----------|------|
| `NotFoundError` | 404 |
| `ValidationError` | 422 |
| `RateLimitError` | 429 |
| `PromptInjectionError` | 400 |
| `ServiceUnavailableError` | 503 |
| `AppError` (base) | 500 |

Raise these from services and endpoints instead of `HTTPException`.

## Subfolders
- [api/](api/README.md): routes
- [config/](config/README.md): settings
- [models/](models/README.md): API request/response schemas
- [services/](services/README.md): business logic
- `prompts/`, `rag/`, `ingestion/`, `retrieval/`, `security/`: empty placeholder packages (the real code lives under `services/`)
