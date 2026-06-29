from dataclasses import dataclass, field

from app.services.retrieval.models import RetrievedChunk


@dataclass
class SynthesisResult:
    answer: str
    source_chunks: list[RetrievedChunk] = field(default_factory=list)
    latency_ms: float = 0.0
