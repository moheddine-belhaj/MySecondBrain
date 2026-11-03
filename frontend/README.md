# Frontend

Nuxt 3 (Vue 3, TypeScript strict) web UI for the Second Brain. It talks to the FastAPI [backend](../backend/README.md) over REST and SSE.

## Stack
Nuxt 3, Pinia (state), Tailwind CSS + typography plugin, VueUse, `marked` (markdown rendering).

## Pages
| Route | File | Purpose |
|-------|------|---------|
| `/` | `pages/index.vue` | RAG chat with streamed answers and cited sources |
| `/search` | `pages/search.vue` | Search the vault, with top-k, score and tag filters |
| `/settings` | `pages/settings.vue` | API health, vault scan and ingest, theme |

## Layout
| Path | Purpose |
|------|---------|
| [components/](components/README.md) | Vue components |
| [composables/](composables/README.md) | Reusable logic (streaming, markdown, theme, health) |
| [stores/](stores/README.md) | Pinia stores |
| [services/](services/README.md) | API client |
| [types/](types/README.md) | TypeScript types mirroring the API |
| `pages/`, `layouts/default.vue` | Routes and the shell (sidebar, header) |
| `assets/css/main.css` | Global styles |
| `app.vue` | Root component |

## Configuration
| Variable | Default |
|----------|---------|
| `NUXT_PUBLIC_API_BASE` | `http://localhost:8000/api/v1` |

It is read in `nuxt.config.ts` as `runtimeConfig.public.apiBase`. In Docker it is baked into the browser bundle, so it must be reachable from the browser (localhost, not a container name).

## Commands
```bash
npm install
npm run dev        # http://localhost:3000
npm run build
npm run typecheck
npm run lint
```
The backend must be running and allow the frontend origin via `ALLOWED_ORIGINS`.
