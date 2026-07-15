from pydantic import BaseModel


class RetrievedChunkResponse(BaseModel):
    """Public search result — internal vector IDs (chunk_id, note_id) are excluded.

    chunk_id is an internal SHA-256 hash used as the Qdrant point key.
    Exposing it would leak the internal keying scheme and could be used
    to correlate results across requests. Clients can uniquely identify a
    chunk by (note_path, chunk_index) without needing the raw DB key.
    """
    score: float
    rank: int
    chunk_text: str
    note_title: str
    note_path: str
    tags: list[str]
    heading_path: list[str]
    chunk_index: int
    total_chunks: int
    word_count: int
    note_modified_at: str


class SearchResponse(BaseModel):
    query: str
    results: list[RetrievedChunkResponse]
    total_candidates: int
    deduplicated_count: int
    latency_ms: float
    filters_applied: bool
    retrieval_mode: str = "semantic"
    keyword_candidates: int = 0
