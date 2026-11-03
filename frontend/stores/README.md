# stores

Pinia setup-style stores.

| Store | State | Actions |
|-------|-------|---------|
| `chat.ts` | `messages`, `sessionId`, `isLoading`, `error` | `addUserMessage`, `addAssistantPlaceholder`, `appendDelta` (streaming tokens), `finaliseAssistant` (sources and session ID), `setError`, `sendBlocking`, `clearSession` |
| `search.ts` | `query`, `results`, `topK` (5), `scoreThreshold`, `activeTags`, `latencyMs`, counts | `search`, `toggleTag`, `clearFilters`, `clear`. Computed: `availableTags`, `hasActiveFilters`, `activeFilterCount` |
| `ingest.ts` | `status`, `scanResult`, `isIngesting`, `isScanning`, `error` | `triggerIngest`, `scan` |
| `ui.ts` | `theme`, `sidebarOpen` | `setTheme`, `initTheme` (reads `localStorage`), `toggleSidebar` |

Streaming chat is driven from `pages/index.vue` through `useStream`, which feeds `appendDelta` and `finaliseAssistant`. `sendBlocking` is the non-streaming fallback.
