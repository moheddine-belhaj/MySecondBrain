# types

`index.ts` holds the shared TypeScript types, mirroring the backend schemas in `backend/app/models/`.

- Chat: `ChatMessage`, `RagChatRequest`, `ChatResponse`, `NoteSource`, `StreamEvent` (`retrieval`, `delta`, `done` or `error`), `UiChatMessage`, `ConversationHistory`, `SessionInfo`
- Search: `SearchRequest`, `RetrievedChunk`, `SearchResponse`
- Ingest and system: `IngestStatus`, `ScanResponse`, `HealthResponse`
- UI: `Theme` (`light`, `dark` or `system`), `ApiError`

Update these when the backend response models change.
