from pydantic import BaseModel


class RetrievedChunkResponse(BaseModel):
    chunk_id: str
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
