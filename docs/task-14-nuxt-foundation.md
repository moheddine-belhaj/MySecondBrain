# Task 14 — Nuxt Frontend Foundation

## What Was Built

A complete Nuxt 3 frontend foundation for the Second Brain RAG application. Full dark/light mode, responsive layout, typed API service layer, Pinia state management, SSE streaming composable, and three functional pages (Chat, Search, Settings). No mock data — all wired to the FastAPI backend.

---

## Stack

| Layer | Choice | Reason |
|---|---|---|
| Framework | Nuxt 3 | File-based routing, auto-imports, SSR-ready |
| UI | Vue 3 Composition API (`<script setup>`) | Ergonomic reactive primitives |
| Styling | TailwindCSS v3 | Utility-first, dark mode via `class` strategy |
| State | Pinia | Vue 3-native, DevTools-friendly |
| Types | TypeScript strict mode | Matches backend API shapes exactly |
| Utilities | VueUse | Reactive browser APIs (future use) |

---

## Folder Structure

```
frontend/
├── app.vue                      # Root entry — mounts layout + page
├── nuxt.config.ts               # Modules, runtime config, CSS, head
├── tailwind.config.ts           # darkMode: "class", content paths, brand colours
├── package.json
│
├── assets/css/main.css          # Tailwind directives + base/component layer
│
├── types/index.ts               # All TypeScript interfaces (mirrors backend models)
│
├── services/
│   └── api.ts                   # Typed fetch wrappers: chatApi, searchApi, ingestApi, healthApi
│
├── stores/
│   ├── ui.ts                    # Theme (light/dark/system), sidebar open state
│   ├── chat.ts                  # Messages, session ID, streaming state
│   ├── search.ts                # Query, results, loading
│   └── ingest.ts                # Ingest/scan status
│
├── composables/
│   ├── useStream.ts             # SSE fetch reader (ReadableStream decoder)
│   ├── useTheme.ts              # isDark, toggle, set — reads from useUiStore
│   └── useHealth.ts             # Backend health check
│
├── layouts/
│   └── default.vue              # Sidebar + Header shell; initialises theme on mount
│
├── components/
│   ├── layout/
│   │   ├── AppSidebar.vue       # Nav links, collapse toggle
│   │   └── AppHeader.vue        # Page title, dark mode toggle button
│   └── ui/
│       └── AppIcon.vue          # Inline SVG icon component (no icon library dep)
│
└── pages/
    ├── index.vue                # Chat page — streaming RAG chat
    ├── search.vue               # Semantic search page
    └── settings.vue             # Health, vault ingest, theme picker
```

---

## Architecture

### Dark Mode

TailwindCSS `darkMode: "class"` strategy. The `useUiStore` reads the saved preference from `localStorage`, falls back to `prefers-color-scheme`, and toggles the `.dark` class on `<html>`. Initialisation fires in `onMounted` inside `layouts/default.vue` so it runs client-side only — avoids SSR hydration mismatches.

```
User preference (localStorage) → useUiStore.initTheme()
                                → applyTheme() → document.documentElement.classList.toggle("dark")
                                → Tailwind dark: classes activate
```

### API Service Layer

`services/api.ts` exports four namespaced objects: `chatApi`, `searchApi`, `ingestApi`, `healthApi`. Each uses Nuxt's `$fetch` (built on `ofetch`) with full TypeScript generics. The base URL comes from `useRuntimeConfig().public.apiBase`, which reads from `.env` at build time.

### SSE Streaming

`composables/useStream.ts` wraps the native `fetch` + `ReadableStream` API:

```
fetch POST /chat/rag/stream
  → ReadableStream reader
  → TextDecoder (stream: true)
  → line buffer → split on \n → filter "data: " prefix
  → JSON.parse → StreamEvent → onEvent callback
  → event.done = true → onDone()
```

The `useChatStore` owns the message list. The chat page creates a streaming placeholder message, appends deltas via `appendDelta()`, then finalises it with sources when `done` fires.

### Pinia Stores

| Store | Owns |
|---|---|
| `useUiStore` | theme, sidebarOpen |
| `useChatStore` | messages[], sessionId, isLoading, streaming helpers |
| `useSearchStore` | query, results[], total, isLoading |
| `useIngestStore` | ingest status, scan result, isIngesting, isScanning |

All stores use the Composition API form (`defineStore("id", () => {...})`).

### Component Design

- `AppIcon` — inline SVG paths, no external icon library. Add new icons in the `icons` record.
- `AppSidebar` — collapses to icon-only rail (56px) or full width (224px). State in `useUiStore`.
- `AppHeader` — displays the current page title (computed from route) + dark mode toggle.
- `layouts/default.vue` — flex row (sidebar + content column). Content column = header + scrollable main.

---

## Pages

### Chat (`/`)
Full streaming RAG chat. Sends `POST /chat/rag/stream` via `useStream`. Renders user/assistant bubbles, typing indicator (bouncing dots while streaming), and source citations below each assistant reply. Enter sends, Shift+Enter adds newline. Clears session with the X button.

### Search (`/search`)
Semantic vault search. Sends `GET /search?q=...&top_k=N`. Displays relevance score (%), heading breadcrumbs, note path, chunk text, and tags for each result.

### Settings (`/settings`)
Three panels:
1. **Backend Status** — live health check against `/health`. Shows per-component status (Qdrant, Ollama, etc.)
2. **Vault Ingest** — trigger `POST /ingest` or `POST /ingest/scan`. Shows result inline.
3. **Appearance** — Light / Dark / System theme selector, persisted to localStorage.

---

## TypeScript Types (`types/index.ts`)

All types mirror the backend Pydantic models exactly (using `snake_case` keys as they come over the wire):

| Interface | Backend model |
|---|---|
| `ChatMessage` | `ChatMessage` |
| `NoteSource` | `NoteSource` |
| `RagChatRequest` | `RagChatRequest` |
| `ChatResponse` | `RagChatResponse` |
| `StreamEvent` | `StreamEvent` |
| `UiChatMessage` | UI-only (adds id, isStreaming, createdAt) |
| `RetrievedChunk` | `RetrievedChunkResponse` |
| `SearchResponse` | `SearchResponse` |
| `IngestStatus` | `IngestStatus` |
| `ScanResponse` | `ScanResponse` |
| `HealthResponse` | Health endpoint shape |
| `Theme` | `"light" \| "dark" \| "system"` |

---

## How to Test This Task

### 1. Prerequisites

- Backend running on port 8000: `cd backend && uvicorn app.main:app --reload`
- Node 20+: `node --version`

### 2. Start the frontend dev server

```bash
cd frontend
npm install       # only needed once
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

### 3. Dark mode

- Click the 🌙 icon in the top-right header → page switches to dark
- Click ☀️ → switches back to light
- Go to Settings → Appearance → pick System/Light/Dark
- Close and reopen the tab — theme persists (localStorage)
- Check `<html>` in DevTools → should have `class="dark"` when dark mode is active

### 4. Sidebar

- Click the collapse chevron at the bottom of the sidebar → collapses to icon-only rail
- Click again → expands back
- Navigate between Chat / Search / Settings — active link is highlighted

### 5. Chat (streaming)

- Make sure the backend is running and vault is ingested
- Type a question about your notes, press Enter
- Three bouncing dots appear while streaming
- Answer streams in word-by-word
- Source citations appear below the answer
- Click X to clear the conversation

### 6. Search

- Navigate to `/search`
- Type a keyword from your vault, press Enter
- Results appear with score, heading path, chunk text, tags
- Change Top 3/5/10 selector and search again — result count changes

### 7. Settings / Health

- Navigate to `/settings`
- Backend status panel shows green ✓ if Qdrant + Ollama are running
- Click "Scan Vault" → see the list of notes found
- Click "Ingest Vault" → triggers re-indexing

### 8. TypeScript check

```bash
cd frontend
npm run typecheck
```

Should report 0 errors.

---

## Manual Configuration

### Required before first run

```bash
cd /home/moheddine/Desktop/projects/llm/frontend
npm install
```

### Environment variable (optional — default works for local dev)

Create `frontend/.env` only if you run the backend on a different host/port:

```env
NUXT_PUBLIC_API_BASE=http://localhost:8000/api/v1
```

Without this file, the default `http://localhost:8000/api/v1` is used.

### Backend CORS

The backend already has `http://localhost:3000` in `ALLOWED_ORIGINS` (set in `backend/.env`). No changes needed.

### Node version

Node 20 is required. The `package.json` lists Nuxt 3.14 which declares `node >= 22` in its own metadata, but runs correctly on Node 20 — the `npm warn EBADENGINE` is a warning, not an error.

If you want to suppress it, upgrade Node via nvm:

```bash
nvm install 22
nvm use 22
```
