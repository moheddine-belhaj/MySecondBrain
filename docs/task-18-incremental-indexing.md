# Task 18 — Incremental Indexing

## Goal

Avoid full vault reprocessing on every ingest run. Detect which notes changed since the last run and process only those — new, modified, and deleted — skipping everything unchanged.

---

## Files Changed

| File | Action |
|---|---|
| `backend/app/services/indexing/__init__.py` | New package |
| `backend/app/services/indexing/state_store.py` | New — JSON state persistence |
| `backend/app/services/indexing/sync_engine.py` | New — incremental diff + embed engine |
| `backend/app/config/settings.py` | Added `index_state_path`, `sync_interval_minutes` |
| `backend/app/models/ingest.py` | Added `SyncStatus` response model |
| `backend/app/api/v1/endpoints/ingest.py` | Added `POST /ingest/sync`, `GET /ingest/sync/status` |
| `backend/app/main.py` | Wired sync engine + background scheduler into lifespan |
| `backend/app/.env.example` | Documented new env vars |
| `backend/data/.gitkeep` | Created `data/` directory for state file |
| `.gitignore` | Added `backend/data/index_state.json` |

---

## Architecture

### Hashing Strategy

`VaultScanner` already computed SHA-256 of raw file bytes per note (`content_hash`). This is reused — no new hashing code. The hash changes whenever content, encoding, or line endings change, giving reliable change detection with no false negatives.

### State Store (`IndexStateStore`)

Persists `{note_path → content_hash}` as a JSON file at `./data/index_state.json`.

- **Why JSON?** Simple, human-readable, inspectable. No extra dependencies. The data is a flat string→string dict — SQLite would be overkill.
- **Why file-based (not Qdrant)?** Keeps state separate from the search index. If the Qdrant collection is wiped and rebuilt, the state file is also deleted or reset — they stay in sync.
- **Atomic writes**: Python's `os.replace()` (POSIX rename) ensures the file is never visible in a half-written state. A crash mid-save leaves the old file intact.

### Diff Algorithm (`IncrementalSyncEngine`)

```
current   = {path: hash}  ← from VaultScanner (live disk scan)
persisted = {path: hash}  ← from IndexStateStore (last run)

new_paths      = current − persisted            → embed + index
deleted_paths  = persisted − current            → delete from Qdrant
modified_paths = common where hash differs      → delete old + embed new
unchanged      = common where hash matches      → skip entirely
```

Processing order: **delete first, then embed**. This prevents a window where old chunks and new chunks coexist for the same note.

### Failure Safety

If the server crashes between "embed success" and "save state":
- The notes were indexed but state wasn't updated.
- Next run: those notes appear as "modified" → old chunks deleted (no-op, already gone), re-embedded and re-indexed (idempotent upsert).
- Converges to correct state.

If the server crashes mid-embed:
- State is not saved.
- Next run: those notes re-appear as "new" or "modified" and are re-processed.
- Converges to correct state.

### Scheduling (`_auto_sync_loop`)

Uses an `asyncio.create_task` loop in the FastAPI lifespan — no external scheduler dependency (APScheduler, Celery, Redis, etc.).

```python
# In main.py lifespan:
if settings.sync_interval_minutes > 0:
    sync_task = asyncio.create_task(
        _auto_sync_loop(sync_engine, sync_interval_minutes * 60)
    )
```

The task sleeps first, then syncs — so the first sync on startup is always manual (unless you call `POST /ingest/sync`). The task is cancelled cleanly on shutdown.

**To enable**: set `SYNC_INTERVAL_MINUTES=30` in `.env` (or any non-zero value).

---

## New API Endpoints

### `POST /ingest/sync`
Runs an incremental sync. Rate-limited (same as full ingest). Returns `SyncStatus`.

```json
{
  "status": "completed",
  "new_notes": 3,
  "modified_notes": 1,
  "deleted_notes": 0,
  "unchanged_notes": 142,
  "new_chunks": 28,
  "duration_ms": 1840.3,
  "last_run_at": "2026-07-10T14:32:00Z",
  "scheduler_active": false,
  "sync_interval_minutes": 0,
  "message": null
}
```

Status values:
- `completed` — changes found and processed successfully
- `no_changes` — all notes unchanged, nothing done
- `failed` — one or more batches had errors (partial index may have been written)
- `never_run` — no sync has run in this server session (status endpoint only)

### `GET /ingest/sync/status`
Returns the result of the most recent sync without triggering a new one. Returns `never_run` if no sync has run since the server started.

---

## Configuration

| Setting | Default | Description |
|---|---|---|
| `INDEX_STATE_PATH` | `./data/index_state.json` | Where the state file is written |
| `SYNC_INTERVAL_MINUTES` | `0` | Auto-sync interval (0 = disabled) |

---

## Difference from Full Ingest (`POST /ingest`)

| | `POST /ingest` | `POST /ingest/sync` |
|---|---|---|
| Processes | All notes every time | Only new/modified/deleted |
| Uses state file | No | Yes |
| Stale chunk cleanup | Set-difference across all IDs | Per-note delete by `note_id` |
| Good for | First-time index, forced rebuild | Daily use, auto-sync |
| Speed on unchanged vault | Slow (re-embeds everything) | Fast (skips all embedding) |

---

## Example: First Run vs Second Run

**Run 1** (100 notes, no state file):
- All 100 notes appear as "new"
- 100 notes embedded, ~800 chunks indexed
- State file written: 100 entries

**Run 2** (100 notes, 2 changed, 1 deleted, 97 unchanged):
- 97 notes → skipped
- 2 notes → old chunks deleted, re-embedded
- 1 note → old chunks deleted from Qdrant
- State file updated: 99 entries

Run 2 takes ~2% of the work of Run 1.
