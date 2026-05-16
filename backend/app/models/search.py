from pydantic import BaseModel


class SearchResult(BaseModel):
    note_title: str
    note_path: str
    excerpt: str
    score: float
