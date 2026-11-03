# models

Pydantic schemas for the **public API** (request and response bodies). Internal domain models live next to their service.

| File | Contents |
|------|----------|
| `chat.py` | `ChatMessage`, `ChatRequest/Response`, `RagChatRequest/Response`, `NoteSource`, `StreamEvent` + `StreamEventType` (SSE payloads), `SessionInfo`, `ConversationHistory` |
| `search.py` | `SearchResponse`, `RetrievedChunkResponse` (internal chunk/note IDs are hidden) |
| `ingest.py` | `ScanResponse`, `NotePreview`, `ChunkingPreviewResponse`, `IngestStatus`, `SyncStatus` |
