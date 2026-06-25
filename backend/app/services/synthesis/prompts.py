"""Prompt templates for RAG synthesis.

Architecture — three separated layers
--------------------------------------
Every prompt assembled here is built from three distinct, named sections:

  Layer 1 · SYSTEM_INSTRUCTIONS
      Persona, rules, anti-hallucination constraints, citation format.
      Fixed at startup; never changes per request.

  Layer 2 · Context section
      Retrieved note excerpts formatted by ContextBuilder and injected at
      runtime via the {context_str} variable.  Token-capped before reaching
      here, so context overflow is impossible.

  Layer 3 · User section
      The raw question, injected via {query_str}.  No pre-processing beyond
      the retrieval query passed from the endpoint.

The three layers are exposed as module-level constants so they can be
inspected, tested, and overridden independently.

LlamaIndex variable names (do not rename)
------------------------------------------
  text_qa_template : {context_str}, {query_str}
  refine_template  : {context_msg}, {query_str}, {existing_answer}

Citation format
---------------
ContextBuilder numbers each chunk block [1], [2], etc.  The instructions
here tell the model to cite inline ("according to [1]") so that citations
map directly back to specific note excerpts in the API sources list.

Hallucination reduction
-----------------------
Three explicit constraints minimise hallucination:
  1. "Use ONLY the provided excerpts" — no outside knowledge.
  2. "If context is insufficient, say so" — explicit refusal over guessing.
  3. "Never invent note titles, dates, or facts" — named entity guard.
"""

from llama_index.core import PromptTemplate

# ── Layer 1: System instructions ─────────────────────────────────────────────

SYSTEM_INSTRUCTIONS = (
    "You are a precise AI assistant for a personal Obsidian knowledge base (Second Brain).\n"
    "\n"
    "Rules — follow every rule without exception:\n"
    "1. Answer using ONLY the note excerpts provided below. "
    "Do not use outside knowledge or training data.\n"
    "2. Cite every claim inline by its source number: [1], [2], [1][3], etc. "
    "Place the citation immediately after the sentence it supports.\n"
    "3. If the provided excerpts do not contain enough information, respond with:\n"
    '   "I don\'t have enough information in your notes to answer this."\n'
    "   Do not guess, infer beyond the text, or apologise at length.\n"
    "4. Keep answers concise and well-structured. "
    "Use bullet points or numbered lists when enumerating items.\n"
    "5. Never invent note titles, dates, names, or facts not found in the excerpts."
)

# ── Layer 2: Context section markers ─────────────────────────────────────────

_CONTEXT_HEADER = "Note excerpts from the knowledge base (cite by [N]):"
_CONTEXT_FENCE = "=" * 60
_CONTEXT_FOOTER = (
    "(End of excerpts — your answer must be grounded in the above only)"
)

# ── Layer 3: Response format instruction ──────────────────────────────────────

_ANSWER_INSTRUCTION = (
    "Answer"
    " (cite each source as [1], [2], etc."
    " — if the context is insufficient, say so explicitly):"
)

# ── Assembled LlamaIndex templates ────────────────────────────────────────────

QA_PROMPT = PromptTemplate(
    f"{SYSTEM_INSTRUCTIONS}\n\n"
    f"{_CONTEXT_HEADER}\n"
    f"{_CONTEXT_FENCE}\n"
    "{context_str}\n"
    f"{_CONTEXT_FENCE}\n"
    f"{_CONTEXT_FOOTER}\n\n"
    "Question: {query_str}\n\n"
    f"{_ANSWER_INSTRUCTION}"
)

REFINE_PROMPT = PromptTemplate(
    "Original question: {query_str}\n\n"
    "Partial answer so far:\n"
    "{existing_answer}\n\n"
    "Additional note excerpts:\n"
    f"{_CONTEXT_FENCE}\n"
    "{context_msg}\n"
    f"{_CONTEXT_FENCE}\n\n"
    "Refine the answer only if the new excerpts add relevant, non-redundant "
    "information. Otherwise return the existing answer unchanged. "
    "Keep citations as [N].\n\n"
    "Refined answer:"
)
