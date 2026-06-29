"""Context injection strategy for RAG synthesis.

Responsibilities
----------------
1. Format each RetrievedChunk into a numbered citation block.
2. Estimate cumulative token cost and truncate to stay within the budget.
3. Strip the chunker's breadcrumb prefix — the citation header carries the
   same location information, so showing it twice wastes context tokens.
4. Return a BuiltContext with the formatted string and the exact list of
   chunks that fit (used by the synthesizer for source attribution).

Citation block format (one per chunk)
--------------------------------------

    [1] My Research Note — Key Concepts > Embeddings  (score: 0.92)
    ────────────────────────────────────────────────────────────────────
    chunk body text here …

    [2] Another Note  (score: 0.81)
    ────────────────────────────────────────────────────────────────────
    more body text …

The [N] numbers are referenced in the QA prompt's citation instruction so
the model knows to write "[1]" inline after sentences it draws from that
chunk.  They are also surfaced to the API consumer via the sources list,
allowing the frontend to render numbered footnotes.

Truncation policy
-----------------
Chunks are processed in rank order (already sorted by score by the
RetrievalEngine). Each chunk's estimated token cost is compared against
the remaining budget:

  - Fits fully → include as-is.
  - Does not fit but remaining budget > _MIN_CHUNK_TOKENS → truncate body
    to fill the remainder, mark was_truncated=True, stop processing.
  - Remaining budget < _MIN_CHUNK_TOKENS → discard and stop.
"""

import logging
import re
from dataclasses import dataclass, field

from app.services.retrieval.models import RetrievedChunk
from app.services.synthesis.token_counter import estimate_tokens, truncate_to_token_budget

logger = logging.getLogger("app.services.synthesis")

_SEPARATOR = "─" * 68
_BREADCRUMB_RE = re.compile(r"^\[Note:[^\]]+\]\n\n")
_MIN_CHUNK_TOKENS = 50  # skip partial inclusion if fewer tokens would be added


@dataclass
class BuiltContext:
    """Output of ContextBuilder.build()."""

    context_str: str
    included_chunks: list[RetrievedChunk] = field(default_factory=list)
    total_tokens: int = 0
    was_truncated: bool = False


class ContextBuilder:
    """Formats retrieved chunks into a numbered, token-capped context string."""

    def __init__(self, max_context_tokens: int = 2000) -> None:
        self._max_tokens = max_context_tokens

    def build(self, chunks: list[RetrievedChunk]) -> BuiltContext:
        """Format and token-cap chunks in rank order.

        Returns a BuiltContext whose context_str is ready to drop into
        the {context_str} slot of the QA prompt template.
        """
        blocks: list[str] = []
        included: list[RetrievedChunk] = []
        total_tokens = 0
        was_truncated = False

        for i, chunk in enumerate(chunks, start=1):
            header = _format_citation_header(chunk, i)
            body = _strip_breadcrumb(chunk.chunk_text)
            block = f"{header}\n{_SEPARATOR}\n{body}"
            block_tokens = estimate_tokens(block)
            remaining = self._max_tokens - total_tokens

            if block_tokens <= remaining:
                blocks.append(block)
                included.append(chunk)
                total_tokens += block_tokens
            else:
                # Attempt partial inclusion of this chunk
                overhead = estimate_tokens(f"{header}\n{_SEPARATOR}\n")
                body_budget = remaining - overhead

                if body_budget < _MIN_CHUNK_TOKENS:
                    logger.debug(
                        "Context budget exhausted",
                        extra={
                            "included": len(included),
                            "skipped": len(chunks) - len(included),
                            "remaining_tokens": remaining,
                        },
                    )
                    break

                truncated_body, _ = truncate_to_token_budget(body, body_budget)
                blocks.append(f"{header}\n{_SEPARATOR}\n{truncated_body}")
                included.append(chunk)
                total_tokens += estimate_tokens(blocks[-1])
                was_truncated = True
                break

        context_str = "\n\n".join(blocks)

        logger.debug(
            "Context built",
            extra={
                "chunks_included": len(included),
                "chunks_total": len(chunks),
                "tokens": total_tokens,
                "budget": self._max_tokens,
                "was_truncated": was_truncated,
            },
        )

        return BuiltContext(
            context_str=context_str,
            included_chunks=included,
            total_tokens=total_tokens,
            was_truncated=was_truncated,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _format_citation_header(chunk: RetrievedChunk, citation_num: int) -> str:
    """Build the [N] Title — Section > Sub  (score: X.XX) header line."""
    sections = chunk.heading_path[1:] if len(chunk.heading_path) > 1 else []
    location = f" — {' > '.join(sections)}" if sections else ""
    return f"[{citation_num}] {chunk.note_title}{location}  (score: {chunk.score:.2f})"


def _strip_breadcrumb(text: str) -> str:
    """Remove the '[Note: ...]\n\n' prefix written by MarkdownChunker.

    The citation header already carries title + section info, so the
    in-text breadcrumb is redundant and consumes tokens needlessly.
    """
    return _BREADCRUMB_RE.sub("", text, count=1)
