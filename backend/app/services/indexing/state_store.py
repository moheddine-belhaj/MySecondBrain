"""IndexStateStore — persists {note_path → content_hash} between sync runs.

State is a simple JSON dict mapping each note's POSIX-relative path to its
SHA-256 content hash. Comparing this against the current vault scan tells the
sync engine exactly which notes are new, modified, deleted, or unchanged —
without touching Qdrant at all.

Atomic writes (write temp → rename) prevent a crash mid-save from leaving
a half-written file. On POSIX, os.replace() is atomic; the old file is never
visible in a broken state.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("app.services.indexing.state_store")


class IndexStateStore:
    """Thin file-based key-value store for note path → content hash mappings."""

    def __init__(self, state_path: Path) -> None:
        self._path = state_path

    async def load(self) -> dict[str, str]:
        """Return the persisted state, or an empty dict if none exists yet."""
        return await asyncio.to_thread(self._load_sync)

    async def save(self, state: dict[str, str]) -> None:
        """Atomically overwrite the state file."""
        await asyncio.to_thread(self._save_sync, state)

    @property
    def path(self) -> Path:
        return self._path

    # ── Sync helpers (run in thread pool) ────────────────────────────────────

    def _load_sync(self) -> dict[str, str]:
        if not self._path.exists():
            logger.debug("No state file found — starting fresh", extra={"path": str(self._path)})
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            logger.debug("State loaded", extra={"notes": len(data), "path": str(self._path)})
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "State file unreadable — starting fresh",
                extra={"path": str(self._path), "error": str(exc)},
            )
            return {}

    def _save_sync(self, state: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._path)  # atomic on POSIX
        logger.debug("State saved", extra={"notes": len(state), "path": str(self._path)})
