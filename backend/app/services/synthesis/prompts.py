"""LlamaIndex prompt templates for RAG synthesis.

LlamaIndex's CompactAndRefine mode uses two templates:
  text_qa_template — used for the first (or only) context window pass.
  refine_template  — used when context exceeds one window; refines a partial answer
                     with additional context chunks.

Variable names are fixed by LlamaIndex:
  text_qa_template  : {context_str}, {query_str}
  refine_template   : {context_msg}, {query_str}, {existing_answer}
"""

from llama_index.core import PromptTemplate

QA_PROMPT = PromptTemplate(
    "You are a helpful AI assistant for a personal Obsidian knowledge base (Second Brain).\n"
    "Answer the question using ONLY the provided note excerpts.\n"
    "Cite the source note when you use information from it.\n"
    "If the provided context does not contain enough information, say so clearly — "
    "do not fabricate details.\n\n"
    "---------------------\n"
    "Note excerpts:\n"
    "{context_str}\n"
    "---------------------\n\n"
    "Question: {query_str}\n\n"
    "Answer:"
)

REFINE_PROMPT = PromptTemplate(
    "You are refining an answer about a personal Obsidian knowledge base.\n"
    "The original question was: {query_str}\n\n"
    "Existing partial answer:\n"
    "{existing_answer}\n\n"
    "Additional note excerpts (use only if they add new, relevant information):\n"
    "---------------------\n"
    "{context_msg}\n"
    "---------------------\n\n"
    "Refine the answer if the new excerpts add useful information; "
    "otherwise return the existing answer unchanged.\n\n"
    "Refined answer:"
)
