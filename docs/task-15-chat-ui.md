# Task 15 — Chat UI

## What Was Built

A complete, production-quality chat interface wired to the streaming RAG backend. Markdown rendering, typing indicators, auto-scroll with user-override, animated source citations, copy-to-clipboard, inline error handling, dark mode, and a clean developer-focused aesthetic.

---

## New Files

| File | Role |
|---|---|
| `composables/useMarkdown.ts` | `marked` wrapper — GFM + line breaks; strips raw HTML |
| `components/chat/TypingIndicator.vue` | Animated three-dot typing indicator |
| `components/chat/ChatSources.vue` | Collapsible source citation cards with score bars |
| `components/chat/ChatMessageContent.vue` | Markdown renderer for assistant; plain text for user |
| `components/chat/ChatMessage.vue` | Full message row: avatar, bubble, sources, copy button |
| `components/chat/ChatMessages.vue` | Scrollable list with smart auto-scroll + empty state |
| `components/chat/ChatInput.vue` | Auto-resize textarea, char counter, spinner, Enter to send |

## Modified Files

| File | Change |
|---|---|
| `pages/index.vue` | Full rewrite — clean orchestrator using chat components |
| `stores/chat.ts` | Added `setError(id, text)` for inline message-level errors |
| `types/index.ts` | Added `error?: string` to `UiChatMessage` |
| `components/ui/AppIcon.vue` | Added `chevron-down`, `chevron-up`, `send`, `copy`, `alert`, `book`, `trash` |
| `tailwind.config.ts` | Added `@tailwindcss/typography` plugin + prose colour overrides |
| `assets/css/main.css` | Added `prose-chat` utility, terminal code blocks, streaming cursor |

---

## UI Architecture

### Component Tree

```
pages/index.vue                    ← Orchestrator: owns stream lifecycle + error state
│
├── ChatMessages.vue               ← Scrollable container, auto-scroll logic, empty state
│   └── ChatMessage.vue [×N]       ← One row per message (avatar + bubble + meta)
│       ├── TypingIndicator.vue    ← Shown while isStreaming && !content
│       ├── ChatMessageContent.vue ← markdown (assistant) or plain text (user)
│       └── ChatSources.vue        ← Collapsible citation cards (assistant only)
│
└── ChatInput.vue                  ← Auto-resize textarea, send button, hints
```

### Data Flow

```
User types → ChatInput emits "send"
           → index.vue: chat.addUserMessage() + chat.addAssistantPlaceholder()
           → useStream.start() → POST /chat/rag/stream
               │
               ├── event.type = "retrieval"  → (ignored at UI level, logged server-side)
               ├── event.type = "delta"      → chat.appendDelta(id, delta)
               │                               → ChatMessageContent re-renders markdown
               │                               → ChatMessages auto-scrolls
               ├── event.type = "done"       → chat.finaliseAssistant(id, sources, session_id)
               │                               → streaming cursor removed, sources appear
               └── event.type = "error"      → chat.setError(id, msg) → error bubble
```

### State Ownership

| State | Lives in | Why |
|---|---|---|
| `messages[]` | `useChatStore` | Persists across re-renders, accessible to all components |
| `sessionId` | `useChatStore` | Sent with every request for conversation continuity |
| `isStreaming` | `useStream` (local ref) | Stream lifecycle is page-scoped |
| `streamError` | `pages/index.vue` (local ref) | Transient — cleared on next send |
| `shouldAutoScroll` | `ChatMessages.vue` (local ref) | UI-only, doesn't belong in the store |
| `open` (sources) | `ChatSources.vue` (local ref) | Per-message UI toggle |
| `copied` | `ChatMessage.vue` (local ref) | Ephemeral 2s feedback |

---

## Features

### Streaming Message Rendering

Deltas from `POST /chat/rag/stream` are appended character-by-character to the assistant placeholder message. The `ChatMessageContent` component re-renders markdown on every delta via `computed(() => render(content))`. This means markdown structures (headings, code blocks) form progressively as the stream arrives.

**Streaming cursor:** A CSS `::after` pseudo-element on `.streaming-cursor` displays `▌` with a blink animation while `isStreaming && content`. It disappears when the stream finalises.

### Markdown Rendering

`marked` v15 with GFM and `breaks: true`. The `html()` renderer is overridden to return `""` — this prevents any raw HTML in the LLM output from reaching the DOM (defence-in-depth alongside the backend output sanitiser).

Typography is handled by `@tailwindcss/typography` via the `prose-chat` CSS utility class:

| Element | Style |
|---|---|
| `<pre><code>` | Dark terminal (`bg-gray-950`), even in light mode |
| `<code>` (inline) | Brand blue text, subtle background |
| `<a>` | Brand colour, no underline (underline on hover) |
| `<blockquote>` | Left border in brand colour |
| `<table>` | Compact, bordered |

### Typing Indicator

Shows three bouncing dots when `isStreaming === true && content === ""`. Each dot has a staggered `animation-delay` (0 / 160 / 320ms) on an `animate-bounce` keyframe at 0.9s duration. Disappears as soon as the first delta token arrives.

### Auto-scroll

`ChatMessages.vue` tracks user scroll position via `onScroll`. A `shouldAutoScroll` flag is `true` when the user is within 80px of the bottom. It resets to `true` on every new message (to catch the user's own sent message). Content-change watcher (keyed on concatenated content) triggers smooth scroll-to-bottom during streaming.

Effect: if the user scrolls up to read old messages, streaming continues but the view doesn't chase the stream. When they scroll back down, auto-scroll resumes.

### Source Citations

`ChatSources.vue` shows a toggle row `"N sources"` below every assistant message that has sources. Click to expand an animated (`<Transition>`) card list. Each card shows:
- Citation number `[1]`, note title (truncated)
- Score progress bar + percentage (monospace, brand colour)
- Note path (monospace, muted)
- Excerpt (3-line clamp)

### Copy to Clipboard

The `ChatMessage` meta row (visible on group hover) shows a **Copy** button for completed assistant messages. It calls `navigator.clipboard.writeText(content)` and shows a 2-second ✓ Copied confirmation, then resets.

### Error Handling

Three error surfaces:

| Error type | Where | How |
|---|---|---|
| Stream `error` event | Inline in message bubble | `chat.setError()` replaces placeholder content with alert icon + error text |
| Network / HTTP error | Red banner above input | `onError` callback in `useStream` populates `streamError` ref |
| Rate limit (429) | Red banner | Message translated to "Too many requests — please wait." |
| Injection detected (400) | Red banner | Message translated to "Request rejected — your message may contain disallowed content." |

The error banner is dismissible and clears automatically when the user sends their next message.

### Loading States

- **Send button:** Turns to a spinning SVG when `isBusy` (streaming) and text field is empty
- **Send button:** Stays disabled (muted gray) while streaming
- **Textarea:** `disabled` attribute while streaming — prevents double-send
- **Stop button:** Appears in toolbar while streaming; calls `useStream.stop()` which aborts the fetch

### Responsive Layout

- `max-w-3xl mx-auto` constrains the message column — readable on wide screens, full-width on mobile
- Message bubbles cap at `max-w-[78ch]` (character-width aware)
- `px-4 sm:px-6` padding adjusts on small screens
- Input area is sticky at the bottom; `backdrop-blur-sm` for glass effect over scrolled content

---

## Markdown Security

`marked` by default passes raw HTML from the source through to the output. The chat renderer overrides `html()` to return `""`:

```ts
const renderer: Partial<Renderer> = {
  html() { return ""; },
};
marked.use({ renderer });
```

This is the correct approach for LLM output:
- Markdown headings, code, tables, lists — rendered normally
- `<script>`, `<iframe>`, `<img src=...onerror=>` — silently dropped

Combined with the backend `OutputSanitizer` (Task 13), this is defence in depth: the server removes leakage patterns before they reach the client; the client prevents raw HTML from reaching the DOM even if anything slips through.

---

## Testing Steps

Start the full stack first (see Task 14 instructions), then:

### Chat basics
1. Open http://localhost:3000
2. You should see the empty state with the vault icon and three prompt hints
3. Type "What are my notes about?" and press Enter
4. Watch: typing dots appear → first token arrives → dots disappear → content streams in with blinking cursor → cursor disappears on done
5. Sources toggle appears below the answer — click it to expand citation cards

### Markdown rendering
6. Ask "Can you give me a summary in markdown with headings and a code block?"
7. The response should render `##` headings, bullet lists, and dark-background code blocks

### Auto-scroll
8. Send a few messages to build up history
9. Scroll up to read old messages mid-stream
10. Stream continues; page doesn't jump to bottom
11. Scroll back down — auto-scroll resumes immediately

### Copy button
12. Hover over an assistant message — Copy button appears in the meta row
13. Click it — button changes to "✓ Copied" for 2 seconds

### Stop streaming
14. Send a long query — while the response is streaming, click **Stop**
15. Stream halts; response stays truncated; you can send a new message

### Error handling
16. Turn off the backend: kill uvicorn
17. Send a message — red banner appears with a connection error
18. Click **Dismiss** — banner disappears
19. Restart the backend, send again — works normally

### Dark mode
20. Click 🌙 in the header — entire chat switches to dark
21. Code blocks stay dark (they're always dark)
22. Refresh the tab — dark mode persists

### Char limit
23. Paste 3500+ characters into the input — a countdown appears in the input corner
24. Exceed 4000 chars — input border turns red, send button stays disabled

---

## Manual Configuration

No new manual steps beyond what Task 14 required:

```bash
cd frontend
npm install   # already done in Task 14
npm run dev
```

The `marked` and `@tailwindcss/typography` packages are in `package.json` and were installed automatically.
