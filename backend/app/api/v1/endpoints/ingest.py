import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from app.config.settings import settings
from app.models.ingest import (
    ChunkPreview,
    ChunkingPreviewResponse,
    IngestStatus,
    NoteChunkPreview,
    NotePreview,
    ScanResponse,
)
from app.services.ingestion import MarkdownChunker
from app.services.vault import VaultScanner

router = APIRouter()
logger = logging.getLogger("app.api.ingest")


def _resolve_vault() -> Path:
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
    return vault_path


@router.post("/scan", response_model=ScanResponse, summary="Scan vault and preview notes")
async def scan_vault() -> ScanResponse:
    """Recursively scan the Obsidian vault and return parsed note metadata.

    Extracts: title, tags, wikilinks, headings, file hash.
    Does NOT embed or index — read-only preview.
    """
    vault_path = _resolve_vault()
    logger.info("Starting vault scan", extra={"vault": str(vault_path)})

    result = await VaultScanner(vault_path).scan()

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


@router.post(
    "/preview",
    response_model=ChunkingPreviewResponse,
    summary="Preview chunking output before indexing",
)
async def preview_chunks() -> ChunkingPreviewResponse:
    """Scan the vault and run the chunking pipeline. Returns all chunks with metadata.

    Use this to validate chunking strategy before running a full ingest.
    Shows: chunk count per note, heading breadcrumbs, word counts, text previews.
    Does NOT embed or write to Qdrant.
    """
    vault_path = _resolve_vault()
    logger.info("Starting chunk preview", extra={"vault": str(vault_path)})

    scan_result = await VaultScanner(vault_path).scan()
    chunker = MarkdownChunker(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    chunk_results = chunker.chunk_notes(scan_result.notes)

    note_previews: list[NoteChunkPreview] = []
    total_chunks = 0

    for cr in chunk_results:
        total_chunks += cr.total_chunks
        note_previews.append(
            NoteChunkPreview(
                relative_path=cr.note_path,
                title=cr.note_title,
                tags=next(
                    (n.tags for n in scan_result.notes if n.content_hash == cr.note_id),
                    [],
                ),
                content_hash=cr.note_id,
                total_chunks=cr.total_chunks,
                chunks=[
                    ChunkPreview(
                        id=chunk.id,
                        chunk_index=chunk.metadata.chunk_index,
                        heading_path=chunk.metadata.heading_path,
                        word_count=chunk.word_count,
                        text_preview=chunk.text[:200],
                    )
                    for chunk in cr.chunks
                ],
            )
        )

    logger.info(
        "Chunk preview complete",
        extra={"notes": len(chunk_results), "total_chunks": total_chunks},
    )

    return ChunkingPreviewResponse(
        vault_path=str(vault_path),
        notes_found=len(chunk_results),
        total_chunks=total_chunks,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        notes=note_previews,
    )


@router.post("", response_model=IngestStatus, summary="Trigger vault ingestion")
async def trigger_ingest() -> IngestStatus:
    """Trigger full ingestion pipeline (scan → chunk → embed → index).

    Embedding and Qdrant indexing will be wired in Task 7.
    Run POST /ingest/scan to preview notes, or POST /ingest/preview to see chunks.
    """
    return IngestStatus(
        status="pending",
        message="Embedding pipeline not yet implemented. Use POST /ingest/preview to preview chunks.",
    )


@router.get("/status", response_model=IngestStatus, summary="Get ingestion status")
async def ingest_status() -> IngestStatus:
    return IngestStatus(status="pending", message="No ingestion run yet.")
