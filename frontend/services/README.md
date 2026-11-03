# services

`api.ts` is the only place that talks to the backend. The base URL comes from `runtimeConfig.public.apiBase`.

| Export | Calls |
|--------|-------|
| `chatApi.sendMessage` | `POST /chat/rag` |
| `chatApi.streamUrl` | URL of `POST /chat/rag/stream` (used by `useStream`) |
| `chatApi.getSession` / `deleteSession` | `GET` / `DELETE /chat/sessions/{id}` |
| `searchApi.search` | `GET /search` (`q`, `top_k`, `score_threshold`, `tags`) |
| `ingestApi.triggerIngest` / `scan` | `POST /ingest`, `POST /ingest/scan` |
| `healthApi.check` | `GET /health` |

Stores call these functions; components never use `$fetch` directly. See the [backend API](../../backend/app/api/v1/README.md) for the endpoints.
