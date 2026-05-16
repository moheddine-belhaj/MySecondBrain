from typing import Literal

from pydantic import BaseModel


class IngestStatus(BaseModel):
    status: Literal["pending", "running", "completed", "failed"]
    total_notes: int = 0
    processed_notes: int = 0
    message: str | None = None
