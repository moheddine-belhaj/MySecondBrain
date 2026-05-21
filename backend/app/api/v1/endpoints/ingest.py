import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from app.config.settings import settings
from app.exceptions import NotFoundError
from app.models.ingest import IngestStatus, NotePreview, ScanResponse
from app.services.vault import VaultScanner

router = APIRouter()
logger = logging.getLogger("app.api.ingest")


@router.post("/scan", response_model=ScanResponse, summary="Scan vault and preview notes")
async def scan_vault() -> ScanResponse:
    """Recursively scan the Obsidian vault and return parsed note metadata.

    Extracts: title, tags, wikilinks, headings, frontmatter, file hash.
    Does NOT embed or index — this is a read-only preview step.
    """
    vault_path = Path(settings.vault_path).resolve()

    if not vault_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vault path not found: {vault_path}",
        )
    if not vault_path.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Vault path is not a directory: {vault_path}",
        )

    logger.info("Starting vault scan", extra={"vault": str(vault_path)})
    scanner = VaultScanner(vault_path)
    result = await scanner.scan()

    previews = [
        NotePreview(
            relative_path=note.relative_path,
            title=note.title,
            tags=note.tags,
            wikilinks=note.wikilinks,
            heading_count=len(note.headings),
            file_size_bytes=note.file_size_bytes,
            content_hash=note.content_hash,
        )
        for note in result.notes
    ]

    return ScanResponse(
        total_files_scanned=result.total_files_scanned,
        notes_found=len(result.notes),
        skipped_files=result.skipped_files,
        scan_duration_ms=result.scan_duration_ms,
        vault_path=result.vault_path,
        notes=previews,
    )


@router.post("", response_model=IngestStatus, summary="Trigger vault ingestion")
async def trigger_ingest() -> IngestStatus:
    """Trigger full ingestion pipeline (scan → chunk → embed → index).

    Embedding and indexing will be wired in Task 6.
    Run /ingest/scan first to preview what will be ingested.
    """
    return IngestStatus(
        status="pending",
        message="Embedding pipeline not yet implemented. Use POST /ingest/scan to preview notes.",
    )


@router.get("/status", response_model=IngestStatus, summary="Get ingestion status")
async def ingest_status() -> IngestStatus:
    return IngestStatus(status="pending", message="No ingestion run yet.")
