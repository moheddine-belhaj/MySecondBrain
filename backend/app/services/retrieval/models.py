"""Retrieval-layer domain models.

RetrievalQuery   — caller-facing query config (text + tuning knobs).
RetrievedChunk   — one ranked result, fully enriched with note metadata.
RetrievalResult  — full response: ranked chunks + run metadata.

Pure Python (no Qdrant, no FastAPI). The engine and tests import only these.
"""

from dataclasses import dataclass, field
from typing import Literal

from app.services.vector.models import SearchFilter


@dataclass
class RetrievalQuery:
    """All config for a single retrieval run.

    over_fetch_factor: fetch top_k * factor from Qdrant before dedup so
    there are enough candidates to fill top_k after heading/note dedup.
    max_chunks_per_note: hard cap per note_id in the final result set.

    Hybrid search fields
    --------------------
    mode             : "semantic"  — vector search only (original behaviour)
                       "keyword"   — BM25 only
                       "hybrid"    — both, fused via weighted RRF
    semantic_weight  : RRF weight for the vector ranking (ignored in keyword mode)
    keyword_weight   : RRF weight for the BM25 ranking (ignored in semantic mode)
    rrf_k            : RRF k-parameter (60 is the standard Cormack et al. value)
    """

    text: str
    top_k: int = 10
    score_threshold: float = 0.0
    filters: SearchFilter | None = None
    deduplicate: bool = True
    max_chunks_per_note: int = 2
    over_fetch_factor: int = 3
    mode: Literal["semantic", "keyword", "hybrid"] = "hybrid"
    semantic_weight: float = 0.7
    keyword_weight: float = 0.3
    rrf_k: int = 60


@dataclass
class RetrievedChunk:
    """One ranked retrieval result, self-contained for the LLM context window."""

    chunk_id: str
    score: float
    rank: int                    # 1-based position in the final ranked list
    chunk_text: str              # decorated text: breadcrumb + raw content
    note_title: str
    note_path: str
    note_id: str
    tags: list[str]
    heading_path: list[str]      # breadcrumb: [H1, H2, H3, …]
    chunk_index: int
    total_chunks: int
    word_count: int
    indexed_at: str
    note_modified_at: str


@dataclass
class RetrievalResult:
    """Outcome of one retrieval run, including observability metadata."""

    query: str
    chunks: list[RetrievedChunk]
    total_candidates: int        # raw hits before dedup (semantic + keyword combined)
    deduplicated_count: int      # chunks removed by deduplicator
    latency_ms: float
    score_threshold: float
    filters_applied: bool
    retrieval_mode: str = "semantic"   # "semantic", "keyword", or "hybrid"
    keyword_candidates: int = 0        # raw BM25 hits (0 for pure semantic)
