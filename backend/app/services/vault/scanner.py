"""Vault scanner — walks the Obsidian vault directory and produces VaultNote objects.

Design principles
-----------------
- The synchronous core (_scan_sync, _parse_file) contains all logic and is
  directly testable without an event loop.
- The public `scan()` method wraps the sync core in asyncio.to_thread so it
  never blocks the FastAPI event loop during a full-vault walk.
- Parse failures are logged and counted as skipped — a single corrupt note
  must never abort the whole scan.
- File hashing (SHA-256 of raw bytes) gives each note a stable content-
  addressable ID. Comparing stored hashes to current hashes is all that is
  needed for incremental indexing in later tasks.
"""

import asyncio
import hashlib
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from app.services.vault.models import ScanResult, VaultNote
from app.services.vault.parser import MarkdownParser

logger = logging.getLogger("app.services.vault")

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".md"})


class VaultScanner:
    def __init__(self, vault_path: Path) -> None:
        self._vault = vault_path.resolve()

    # ── Public async API ──────────────────────────────────────────────────────

    async def scan(self) -> ScanResult:
        """Non-blocking scan. Runs the sync walk in a thread pool worker."""
        return await asyncio.to_thread(self._scan_sync)

    # ── Sync core (unit-testable) ─────────────────────────────────────────────

    def _scan_sync(self) -> ScanResult:
        start = time.perf_counter()
        notes: list[VaultNote] = []
        total = 0
        skipped = 0

        for path in sorted(self._vault.rglob("*")):
            if not path.is_file():
                continue

            # Skip hidden files and Obsidian's own metadata directory
            if any(part.startswith(".") for part in path.parts):
                continue

            total += 1

            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                skipped += 1
                logger.debug("Skipping unsupported file", extra={"path": str(path)})
                continue

            try:
                note = self._parse_file(path)
                notes.append(note)
            except Exception as exc:
                skipped += 1
                logger.warning(
                    "Failed to parse vault file",
                    extra={"path": str(path), "error": str(exc)},
                )

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "Vault scan complete",
            extra={
                "notes": len(notes),
                "skipped": skipped,
                "total": total,
                "duration_ms": elapsed_ms,
                "vault": str(self._vault),
            },
        )
        return ScanResult(
            notes=notes,
            total_files_scanned=total,
            skipped_files=skipped,
            scan_duration_ms=elapsed_ms,
            vault_path=str(self._vault),
        )

    def _parse_file(self, path: Path) -> VaultNote:
        raw_bytes = path.read_bytes()
        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        raw_text = raw_bytes.decode("utf-8", errors="replace")

        stat = path.stat()
        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

        frontmatter, body = MarkdownParser.extract_frontmatter(raw_text)
        headings = MarkdownParser.extract_headings(body)
        wikilinks = MarkdownParser.extract_wikilinks(body)
        tags = MarkdownParser.extract_tags(frontmatter, body)
        title = MarkdownParser.derive_title(frontmatter, headings, path.stem)
        created_at = MarkdownParser.parse_datetime(
            frontmatter.get("created") or frontmatter.get("date")
        )

        return VaultNote(
            path=path,
            relative_path=path.relative_to(self._vault).as_posix(),
            title=title,
            raw_content=raw_text,
            frontmatter=frontmatter,
            tags=tags,
            wikilinks=wikilinks,
            headings=headings,
            content_hash=content_hash,
            file_size_bytes=stat.st_size,
            modified_at=modified_at,
            created_at=created_at,
        )
