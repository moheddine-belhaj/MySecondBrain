# components

Auto-imported without folder prefix (`pathPrefix: false`), so `<ChatInput />` works anywhere.

| Folder | Components |
|--------|------------|
| `chat/` | `ChatMessages` (list), `ChatMessage` (one bubble), `ChatMessageContent` (rendered markdown), `ChatSources` (cited notes), `ChatInput`, `TypingIndicator` |
| `search/` | `SearchInput`, `SearchFilters` (top-k, score, tags), `SearchResults`, `SearchResult` (one hit) |
| `layout/` | `AppSidebar` (navigation), `AppHeader` (page title, theme toggle) |
| `ui/` | `AppIcon`, a shared icon component used by name (e.g. `name="search"`) |

Components are presentational: state lives in [stores/](../stores/README.md), and pages wire them together.
