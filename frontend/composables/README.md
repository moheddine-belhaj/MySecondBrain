# composables

Auto-imported helpers.

| File | Purpose |
|------|---------|
| `useStream.ts` | POSTs with `fetch` and parses the SSE response (`data: {...}` lines) into `StreamEvent`s. Provides `start`, `stop` (aborts) and `isStreaming`. Stops on a `done` or `error` event |
| `useMarkdown.ts` | `render()` turns markdown into HTML with `marked`. Raw HTML in the source is dropped, so LLM output cannot inject scripts |
| `useTheme.ts` | `theme`, `isDark`, `toggle()`, `set()` on top of the UI store |
| `useHealth.ts` | `check()` calls the backend health endpoint, exposing `health`, `isHealthy`, `isLoading`, `error` |
