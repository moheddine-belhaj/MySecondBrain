from typing import Annotated

from fastapi import APIRouter, Query

from app.dependencies import ChatRateLimitDep, RetrievalDep, SecurityGuardDep
from app.models.search import RetrievedChunkResponse, SearchResponse
from app.services.retrieval.models import RetrievalQuery
from app.services.security.input_sanitizer import MAX_QUERY_LENGTH
from app.services.vector.models import SearchFilter

router = APIRouter()


@router.get("", response_model=SearchResponse, summary="Semantic search over vault")
async def search(
    retrieval: RetrievalDep,
    guard: SecurityGuardDep,
    _rl: ChatRateLimitDep,
    q: str = Query(..., min_length=1, max_length=MAX_QUERY_LENGTH, description="Natural language search query"),
    top_k: int = Query(default=10, ge=1, le=50, description="Max chunks to return"),
    score_threshold: float = Query(default=0.0, ge=0.0, le=1.0, description="Minimum similarity score"),
    tags: Annotated[list[str] | None, Query(description="Filter by tags (OR match)")] = None,
    note_path: str | None = Query(default=None, description="Filter by exact note path"),
    deduplicate: bool = Query(default=True, description="Deduplicate chunks from the same heading/note"),
) -> SearchResponse:
    # Sanitise + injection-check the query before retrieval
    clean_q = guard.validate_query(q, max_length=MAX_QUERY_LENGTH)

    filters: SearchFilter | None = None
    if tags or note_path:
        filters = SearchFilter(tags=tags or [], note_path=note_path)

    result = await retrieval.retrieve(
        RetrievalQuery(
            text=clean_q,
            top_k=top_k,
            score_threshold=score_threshold,
            filters=filters,
            deduplicate=deduplicate,
        )
    )

    return SearchResponse(
        query=result.query,
        results=[
            RetrievedChunkResponse(
                # chunk_id intentionally omitted — internal vector DB key
                score=c.score,
                rank=c.rank,
                chunk_text=c.chunk_text,
                note_title=c.note_title,
                note_path=c.note_path,
                tags=c.tags,
                heading_path=c.heading_path,
                chunk_index=c.chunk_index,
                total_chunks=c.total_chunks,
                word_count=c.word_count,
                note_modified_at=c.note_modified_at,
            )
            for c in result.chunks
        ],
        total_candidates=result.total_candidates,
        deduplicated_count=result.deduplicated_count,
        latency_ms=result.latency_ms,
        filters_applied=result.filters_applied,
    )
