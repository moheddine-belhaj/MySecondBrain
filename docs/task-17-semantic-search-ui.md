# Task 17 — Semantic Search UI

## Goal

Build a dedicated semantic search page, separate from chat, with instant search, ranked results, filters, note previews, metadata display, and a clean responsive layout.

---

## Files Changed

| File | Action |
|---|---|
| `frontend/types/index.ts` | Fixed `SearchResponse` field names to match backend |
| `frontend/stores/search.ts` | Full rewrite — added filter state, fixed response mapping |
| `frontend/services/api.ts` | Updated `searchApi.search` to send all filter params |
| `frontend/components/search/SearchInput.vue` | New — search bar with spinner, clear button, keyboard shortcuts |
| `frontend/components/search/SearchFilters.vue` | New — Top K buttons, score slider, tag chips |
| `frontend/components/search/SearchResult.vue` | New — result card with score bar, highlighting, metadata footer |
| `frontend/components/search/SearchResults.vue` | New — all states: loading skeletons, results, no results, empty |
| `frontend/pages/search.vue` | Full rewrite — two-column layout, instant search, mobile filters |

---

## Architecture

### Instant Search
`watchDebounced` from `@vueuse/core` (auto-imported via `@vueuse/nuxt`) fires 350ms after the user stops typing. Minimum 2 characters required to avoid noise. `Enter` key bypasses the debounce for immediate response.

### Filter State (Pinia store)
All filter state lives in `useSearchStore`. Three filters:
- `topK` (default 5) — how many results to return
- `scoreThreshold` (default 0.0) — minimum similarity score
- `activeTags` (default []) — restrict to notes with these tags

Each filter change re-triggers `store.search()` if a query is active. Tags use `deep: true` watch since it's an array.

### Available Tags
`availableTags` is a computed derived from the current result set — not a static list. This keeps tags contextually relevant and avoids a separate tags endpoint.

### Score Threshold Slider
UI shows `0–95` (integer steps of 5). Backend receives `0.0–0.95` (float). Mapped via `sliderValue` computed with `get: v * 100` / `set: v / 100`. Uses `@change` (fires on release) rather than `@input` (fires on every drag position) to avoid spamming the API while dragging.

### Two-Column Layout
Desktop: `hidden lg:flex` sidebar (w-60/xl:w-64) with filters + `flex-1` results area. Mobile: filter toggle button with active-count badge → `slide-down` transition panel above results.

### Query Highlighting (XSS safe)
HTML-escape the text first (`&`, `<`, `>`), then inject `<mark>` tags via regex. Safe to render with `v-html` because no raw user content reaches the DOM unescaped.

```ts
function highlightText(text: string, query: string): string {
  const escaped = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  const words = query.trim().split(/\s+/).filter(w => w.length > 1)
    .map(w => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!words.length) return escaped;
  const regex = new RegExp(`(${words.join("|")})`, "gi");
  return escaped.replace(regex, '<mark class="bg-yellow-200 dark:bg-yellow-900/60 ...">$1</mark>');
}
```

### Score Color Coding
| Score | Color |
|---|---|
| ≥ 80% | Emerald (strong match) |
| ≥ 60% | Amber (good match) |
| ≥ 40% | Orange (partial match) |
| < 40% | Gray (weak) |

Applied to both the progress bar at the top of each card and the score badge.

---

## Bug Fixed During Task

**`SearchResponse` type mismatch** — the frontend types defined `chunks`, `total`, `top_k` but the backend returns `results`, `total_candidates`, `deduplicated_count`, `latency_ms`, `filters_applied`. Search was silently returning empty results. Fixed in `types/index.ts` and all store field references updated to match.

---

## Key Components

### `SearchInput.vue`
- `v-model` two-way bound via computed get/set
- Left icon: animated spinner while `loading`, search icon otherwise
- Clear button fades in when input has content (`Transition name="fade"`)
- `Enter` → `emit("search")`, `Escape` → clear + refocus
- Auto-focuses on mount

### `SearchFilters.vue`
- **Top K**: button group (3 / 5 / 10 / 20), active button gets brand color
- **Score threshold**: range slider 0–95 integer → 0.0–0.95 float, label shows "Any score" or "≥ N%"
- **Tags**: chip buttons derived from current results, fade in/out as results change
- "Clear all" link appears only when `hasActive` is true

### `SearchResult.vue`
- Score progress bar (full-width track, colored fill at `score * 100%`)
- Rank pill (monospace), note title, monospace path, score badge
- Heading breadcrumb with chevron separators (only shown if `heading_path` is non-empty)
- Chunk text with query highlighting, "Show more / Show less" at 320 chars
- Tags as `#tag` monospace chips
- Footer: word count, `chunk N / total`, modified date

### `SearchResults.vue`
- **Error state**: red banner with warning icon
- **Loading state**: 4 pulse-animated skeleton cards matching real card shape (no layout jump)
- **Results**: count header + latency (monospace, subtle) + `TransitionGroup` list with fade-up enter animation
- **No results**: icon + message + hint to try a broader query
- **Initial empty**: icon + description + 3 example queries as monospace chips

---

## TypeCheck Result

```
npm run typecheck → 0 errors
```
