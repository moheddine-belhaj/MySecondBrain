from fastapi import APIRouter

from app.models.ingest import IngestStatus

router = APIRouter()


@router.post("", response_model=IngestStatus, summary="Trigger vault ingestion")
async def trigger_ingest() -> IngestStatus:
    # Stub — ingestion pipeline wired in Task 3
    return IngestStatus(
        status="pending",
        message="Ingestion pipeline not yet implemented. Coming in Task 3.",
    )


@router.get("/status", response_model=IngestStatus, summary="Get ingestion status")
async def ingest_status() -> IngestStatus:
    # Stub — real status tracking wired in Task 3
    return IngestStatus(status="pending", message="No ingestion run yet.")
