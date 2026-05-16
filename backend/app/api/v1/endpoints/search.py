from fastapi import APIRouter, Query

from app.models.search import SearchResult

router = APIRouter()


@router.get("", response_model=list[SearchResult], summary="Semantic search over vault")
async def search(
    q: str = Query(..., min_length=1, description="Natural language search query"),
) -> list[SearchResult]:
    # Stub — Qdrant retrieval wired in Task 4
    return []
