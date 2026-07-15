from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.config.settings import settings
from app.dependencies import ChatRateLimitDep, RetrievalDep, SecurityGuardDep
from app.models.search import RetrievedChunkResponse, SearchResponse
from app.services.retrieval.models import RetrievalQuery
from app.services.security.input_sanitizer import MAX_QUERY_LENGTH
from app.services.vector.models import SearchFilter

router = APIRouter()


@router.get("", response_model=SearchResponse, summary="Hybrid search over vault")
async def search(
    retrieval: RetrievalDep,
    guard: SecurityGuardDep,
    _rl: ChatRateLimitDep,
    q: str = Query(..., min_length=1, max_length=MAX_QUERY_LENGTH, description="Natural language search query"),
    top_k: int = Query(default=10, ge=1, le=50, description="Max chunks to return"),
    score_threshold: float = Query(default=0.0, ge=0.0, le=1.0, description="Minimum similarity score (semantic only)"),
    tags: Annotated[list[str] | None, Query(description="Filter by tags (OR match)")] = None,
    note_path: str | None = Query(default=None, description="Filter by exact note path"),
    deduplicate: bool = Query(default=True, description="Deduplicate chunks from the same heading/note"),
    mode: Literal["semantic", "keyword", "hybrid"] | None = Query(
        default=None,
        description="Retrieval mode: semantic (vector only), keyword (BM25 only), hybrid (both). Defaults to server setting.",
    ),
    semantic_weight: float | None = Query(
        default=None, ge=0.0, le=1.0,
        description="RRF weight for the vector ranking (hybrid only). Defaults to server setting.",
    ),
    keyword_weight: float | None = Query(
        default=None, ge=0.0, le=1.0,
        description="RRF weight for the BM25 ranking (hybrid only). Defaults to server setting.",
    ),
) -> SearchResponse:
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
            mode=mode or settings.hybrid_default_mode,  # type: ignore[arg-type]
            semantic_weight=semantic_weight if semantic_weight is not None else settings.hybrid_semantic_weight,
            keyword_weight=keyword_weight if keyword_weight is not None else settings.hybrid_keyword_weight,
            rrf_k=settings.hybrid_rrf_k,
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
        retrieval_mode=result.retrieval_mode,
        keyword_candidates=result.keyword_candidates,
    )
