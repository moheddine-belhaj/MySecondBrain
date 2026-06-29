"""Response synthesizer — LlamaIndex integration layer.

This is the ONLY file in the codebase that imports LlamaIndex.

Design decisions
----------------
LlamaIndex is used exclusively here (response synthesis). Everything else —
vault scanning, chunking, embedding, vector storage, retrieval, context
formatting, and token counting — stays in our own code.

What LlamaIndex gives us here:
  - Async LLM call via LlamaIndexOllama.achat() under the hood.
  - PromptHelper integration (token-aware template filling).
  - RefineMode for multi-pass synthesis when context is split across windows.

What we do before handing off to LlamaIndex:
  - ContextBuilder formats chunks into numbered citation blocks and
    enforces the token budget.  We pass a SINGLE pre-built TextNode to
    LlamaIndex — it never sees individual chunks.  This gives us full
    control over context formatting and overflow prevention without
    fighting LlamaIndex's internal packing logic.

Replacing LlamaIndex later
--------------------------
Swap this file only.  Contract: synthesize(query, chunks) → SynthesisResult.
Everything above the synthesis layer (retrieval, chunking, embedding) is
untouched because they don't import from llama_index.
"""

import logging
import time

from llama_index.core.response_synthesizers import ResponseMode, get_response_synthesizer
from llama_index.core.schema import NodeWithScore, TextNode

from app.services.retrieval.models import RetrievedChunk
from app.services.synthesis.context_builder import ContextBuilder
from app.services.synthesis.models import SynthesisResult
from app.services.synthesis.prompts import QA_PROMPT, REFINE_PROMPT

logger = logging.getLogger("app.services.synthesis")

_FALLBACK_ANSWER = (
    "I couldn't find any relevant information in your notes for this question. "
    "Try rephrasing, lowering the score threshold, or checking that the vault "
    "has been indexed."
)


class ResponseSynthesizer:
    """Thin orchestrator: ContextBuilder → LlamaIndex → SynthesisResult.

    Stateless between calls — safe to construct per-request or reuse.
    """

    def __init__(
        self,
        llm: object,
        mode: str = "compact",
        context_builder: ContextBuilder | None = None,
    ) -> None:
        self._llm = llm
        self._context_builder = context_builder or ContextBuilder()
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
        """Generate an answer grounded in the retrieved chunks.

        Flow:
          1. Empty chunks → return fallback immediately (no LLM call).
          2. ContextBuilder formats + token-caps the chunks.
          3. A single TextNode carrying the pre-built context is passed to
             LlamaIndex; it handles the Ollama call and prompt assembly.
          4. Wrap the response into SynthesisResult with source attribution.
        """
        t_start = time.monotonic()

        if not chunks:
            logger.info(
                "Synthesis: no chunks — returning fallback",
                extra={"query": query[:120]},
            )
            return SynthesisResult(answer=_FALLBACK_ANSWER, source_chunks=[], latency_ms=0.0)

        built = self._context_builder.build(chunks)

        logger.info(
            "Synthesis: start",
            extra={
                "query": query[:120],
                "chunks_in": len(chunks),
                "chunks_used": len(built.included_chunks),
                "context_tokens": built.total_tokens,
                "context_truncated": built.was_truncated,
            },
        )

        # Pre-built context → single node (truncation already handled above)
        node = TextNode(text=built.context_str, id_="context")
        response = await self._synth.asynthesize(
            query, nodes=[NodeWithScore(node=node, score=1.0)]
        )

        latency_ms = round((time.monotonic() - t_start) * 1000, 1)
        answer = response.response or _FALLBACK_ANSWER

        logger.info(
            "Synthesis: complete",
            extra={"latency_ms": latency_ms, "answer_chars": len(answer)},
        )

        return SynthesisResult(
            answer=answer,
            source_chunks=built.included_chunks,
            latency_ms=latency_ms,
        )
