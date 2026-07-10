import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config.settings import settings
from app.dependencies import EmbedDep, IngestRateLimitDep, QdrantDep
from app.models.ingest import (
    ChunkPreview,
    ChunkingPreviewResponse,
    IngestStatus,
    NoteChunkPreview,
    NotePreview,
    ScanResponse,
    SyncStatus,
)
from app.services.indexing import IncrementalSyncEngine
from app.services.ingestion import EmbeddingPipeline, MarkdownChunker
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
async def trigger_ingest(
    embedding_provider: EmbedDep,
    qdrant_service: QdrantDep,
    _rl: IngestRateLimitDep,
) -> IngestStatus:
    """Trigger the full ingestion pipeline: scan → chunk → embed → index.

    Embeddings are generated via Ollama (nomic-embed-text by default).
    Vectors and metadata are stored in Qdrant. Stale chunks from deleted or
    re-chunked notes are automatically removed.

    Run POST /ingest/scan to preview notes, or POST /ingest/preview to see chunks.
    """
    vault_path = _resolve_vault()
    logger.info("Starting ingest pipeline", extra={"vault": str(vault_path)})

    pipeline = EmbeddingPipeline(
        scanner=VaultScanner(vault_path),
        chunker=MarkdownChunker(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        ),
        embedding_provider=embedding_provider,
        qdrant=qdrant_service,
        batch_size=settings.embed_batch_size,
    )

    stats = await pipeline.run()

    final_status = "completed" if not stats.errors else "failed"
    message = (
        f"{len(stats.errors)} batch(es) failed — partial index written."
        if stats.errors
        else None
    )

    logger.info(
        "Ingest pipeline finished",
        extra={"status": final_status, "indexed": stats.indexed_chunks},
    )

    return IngestStatus(
        status=final_status,
        total_notes=stats.total_notes,
        processed_notes=stats.processed_notes,
        total_chunks=stats.total_chunks,
        embedded_chunks=stats.embedded_chunks,
        indexed_chunks=stats.indexed_chunks,
        deleted_stale_chunks=stats.deleted_stale_chunks,
        duration_ms=stats.duration_ms,
        message=message,
    )


@router.get("/status", response_model=IngestStatus, summary="Get ingestion status")
async def ingest_status() -> IngestStatus:
    return IngestStatus(status="pending", message="No ingestion run yet.")


@router.post("/sync", response_model=SyncStatus, summary="Run incremental sync")
async def incremental_sync(
    request: Request,
    _rl: IngestRateLimitDep,
) -> SyncStatus:
    """Detect and index only changed vault content.

    Compares current file hashes against the persisted state from the last
    run. Only new, modified, and deleted notes are processed — unchanged notes
    are skipped entirely.

    Returns counts of new/modified/deleted/unchanged notes, chunks embedded,
    and wall-clock duration. Faster than POST /ingest for incremental updates.
    """
    engine: IncrementalSyncEngine = request.app.state.sync_engine
    stats = await engine.sync()

    status_str: str
    if stats.errors and not stats.has_changes:
        status_str = "failed"
    elif not stats.has_changes:
        status_str = "no_changes"
    else:
        status_str = "failed" if stats.errors else "completed"

    last_run = engine.last_run_at
    scheduler_active = getattr(request.app.state, "sync_task", None) is not None

    return SyncStatus(
        status=status_str,  # type: ignore[arg-type]
        new_notes=stats.new_notes,
        modified_notes=stats.modified_notes,
        deleted_notes=stats.deleted_notes,
        unchanged_notes=stats.unchanged_notes,
        new_chunks=stats.new_chunks,
        duration_ms=stats.duration_ms,
        last_run_at=last_run.isoformat() if last_run else None,
        scheduler_active=scheduler_active,
        sync_interval_minutes=settings.sync_interval_minutes,
        message=f"{len(stats.errors)} error(s) during sync." if stats.errors else None,
    )


@router.get("/sync/status", response_model=SyncStatus, summary="Last sync status")
async def sync_status(request: Request) -> SyncStatus:
    """Return the result of the most recent incremental sync.

    Returns status 'never_run' if no sync has been triggered yet in this
    server session (state file may still exist on disk from a previous run).
    """
    engine: IncrementalSyncEngine = request.app.state.sync_engine
    last_stats = engine.last_stats
    last_run = engine.last_run_at
    scheduler_active = getattr(request.app.state, "sync_task", None) is not None

    if last_stats is None:
        return SyncStatus(
            status="never_run",
            scheduler_active=scheduler_active,
            sync_interval_minutes=settings.sync_interval_minutes,
        )

    status_str = "failed" if last_stats.errors else ("no_changes" if not last_stats.has_changes else "completed")

    return SyncStatus(
        status=status_str,  # type: ignore[arg-type]
        new_notes=last_stats.new_notes,
        modified_notes=last_stats.modified_notes,
        deleted_notes=last_stats.deleted_notes,
        unchanged_notes=last_stats.unchanged_notes,
        new_chunks=last_stats.new_chunks,
        duration_ms=last_stats.duration_ms,
        last_run_at=last_run.isoformat() if last_run else None,
        scheduler_active=scheduler_active,
        sync_interval_minutes=settings.sync_interval_minutes,
        message=f"{len(last_stats.errors)} error(s) during last sync." if last_stats.errors else None,
    )
