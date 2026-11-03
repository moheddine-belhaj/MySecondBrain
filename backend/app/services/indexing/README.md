# services/indexing

Incremental indexing, so only changed notes are re-embedded.

- `state_store.py`: `IndexStateStore` persists `{note_path: content_hash}` as JSON at `INDEX_STATE_PATH` (atomic writes).
- `sync_engine.py`: `IncrementalSyncEngine.sync()` compares the vault with the stored hashes and re-indexes added or changed notes. It deletes the chunks of removed notes and returns `SyncStats`. It can run via `POST /ingest/sync` or on a timer (`SYNC_INTERVAL_MINUTES`).
