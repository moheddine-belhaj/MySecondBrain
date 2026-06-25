"""Response synthesizer — LlamaIndex integration layer.

This is the ONLY file in the codebase that imports LlamaIndex.

Design decisions
----------------
LlamaIndex is used exclusively here (response synthesis). Everything else —
vault scanning, chunking, embedding, vector storage, and retrieval — stays in
our own code because those layers need Obsidian-specific logic and direct
control that LlamaIndex's generic abstractions don't provide.

What LlamaIndex gives us here:
  - Context compaction: stuffs as many chunks as fit in the model's context
    window, then summarises overflow with RefineMode.
  - Prompt management: fills our custom PromptTemplate slots consistently.
  - Token-aware packing: PromptHelper handles context length limits so we don't
    need to manually count tokens before building the prompt.

What we don't use from LlamaIndex:
  - Document loaders   — VaultScanner / VaultParser handle Obsidian specifics.
  - Node parsers       — Chunker produces heading-aware splits.
  - Embedding models   — OllamaService.embed() via EmbeddingProvider ABC.
  - Vector stores      — QdrantService via VectorRepository ABC.
  - Retrieval          — RetrievalEngine (Task 9) with our dedup + ranking.
  - Global Settings    — we pass the LLM explicitly to avoid module-level state.

Replacing LlamaIndex later
--------------------------
Swap this file only. Everything above the synthesis layer is untouched.
The interface contract is: synthesize(query: str, chunks: list[RetrievedChunk])
→ SynthesisResult.
"""

import logging
import time

from llama_index.core.response_synthesizers import ResponseMode, get_response_synthesizer
from llama_index.core.schema import NodeWithScore, TextNode

from app.services.retrieval.models import RetrievedChunk
from app.services.synthesis.models import SynthesisResult
from app.services.synthesis.prompts import QA_PROMPT, REFINE_PROMPT

logger = logging.getLogger("app.services.synthesis")

_FALLBACK_ANSWER = (
    "I couldn't find any relevant information in your notes for this question. "
    "Try rephrasing, lowering the score threshold, or checking that the vault has been indexed."
)


class ResponseSynthesizer:
    """Thin wrapper around LlamaIndex's response synthesizer.

    Accepts our RetrievedChunk objects, converts them to LlamaIndex nodes,
    and delegates answer generation to the configured response mode.

    Stateless between calls — safe to construct per-request.
    """

    def __init__(self, llm: object, mode: str = "compact") -> None:
        self._llm = llm
        self._synth = get_response_synthesizer(
            llm=llm,  # type: ignore[arg-type]
            response_mode=ResponseMode(mode),
            text_qa_template=QA_PROMPT,
            refine_template=REFINE_PROMPT,
            use_async=True,
        )

    async def synthesize(
        self,
        query: str,
        chunks: list[RetrievedChunk],
    ) -> SynthesisResult:
        """Generate an answer from the query and retrieved chunks.

        Returns a fallback message (no LLM call) when there are no chunks,
        rather than sending an empty context to the LLM.
        """
        t_start = time.monotonic()

        if not chunks:
            logger.info("Synthesis: no chunks — returning fallback answer", extra={"query": query[:120]})
            return SynthesisResult(answer=_FALLBACK_ANSWER, source_chunks=[], latency_ms=0.0)

        nodes = [_chunk_to_node(c) for c in chunks]

        logger.info(
            "Synthesis: start",
            extra={"query": query[:120], "nodes": len(nodes)},
        )

        response = await self._synth.asynthesize(query, nodes=nodes)

        latency_ms = round((time.monotonic() - t_start) * 1000, 1)
        answer = response.response or _FALLBACK_ANSWER

        logger.info(
            "Synthesis: complete",
            extra={"latency_ms": latency_ms, "answer_chars": len(answer)},
        )

        return SynthesisResult(
            answer=answer,
            source_chunks=chunks,
            latency_ms=latency_ms,
        )


def _chunk_to_node(chunk: RetrievedChunk) -> NodeWithScore:
    """Convert our RetrievedChunk to a LlamaIndex NodeWithScore.

    Metadata is attached so LlamaIndex's source-formatting helpers can
    reference note titles and paths. The chunk_text becomes the node body
    that is inserted into the context window.
    """
    node = TextNode(
        text=chunk.chunk_text,
        metadata={
            "note_title": chunk.note_title,
            "note_path": chunk.note_path,
            "tags": chunk.tags,
            "heading_path": chunk.heading_path,
            "chunk_id": chunk.chunk_id,
        },
        id_=chunk.chunk_id,
    )
    return NodeWithScore(node=node, score=chunk.score)
