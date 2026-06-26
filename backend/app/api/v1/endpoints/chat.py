"""Chat endpoints — plain and RAG, blocking and streaming.

Endpoint map
------------
POST /chat              — Blocking plain chat with session memory
POST /chat/stream       — Streaming plain chat (SSE) with session memory
POST /chat/rag          — Blocking RAG chat (retrieval + synthesis)
POST /chat/rag/stream   — Streaming RAG chat (SSE): retrieval event → token deltas → done
GET  /chat/sessions/{id} — Fetch conversation history for a session
DELETE /chat/sessions/{id} — Clear a session

SSE wire format (all streaming endpoints)
-----------------------------------------
Each event is a single line:  data: <JSON>\\n\\n
The JSON object is always a StreamEvent.  See models/chat.py for the schema.

Event sequence for /chat/rag/stream:
  1. {"type": "retrieval", "sources": [...], "candidate_count": N}
     — emitted right after vector search; lets the UI show sources while
       the answer still streams.
  2. {"type": "delta", "delta": "<token>", "done": false}
     — one per token chunk from Ollama.
  3. {"type": "done", "done": true, "session_id": "...", "sources": [...]}
     — terminal event; signals the stream is complete.
  4. {"type": "error", "error": "<message>", "done": true}
     — replaces "done" when an unrecoverable error occurs.

Cancellation
------------
Every generator loop checks `await request.is_disconnected()` between tokens.
On disconnect the generator returns early; FastAPI / Starlette closes the
StreamingResponse cleanly.  The partial answer is NOT stored to the session
(incomplete turns cause confusion in follow-up queries).

Session memory
--------------
Sessions are keyed by session_id (UUID).  If the client omits session_id,
a new session is created and its ID is returned in the response / done event.
The session stores the last `max_history` messages (user + assistant pairs).
On each request the last MAX_HISTORY_TURNS pairs are prepended to the LLM
messages so the model has conversation context.
"""

import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.config.settings import settings
from app.dependencies import LLMDep, RetrievalDep, SessionDep, SynthesisDep
from app.models.chat import (
    ChatRequest,
    ChatResponse,
    ConversationHistory,
    NoteSource,
    RagChatRequest,
    RagChatResponse,
    SessionInfo,
    SessionMessageOut,
    StreamEvent,
    StreamEventType,
)
from app.services.llm.schemas import ChatCompletionRequest, LLMMessage, LLMOptions
from app.services.retrieval.models import RetrievalQuery
from app.services.session.store import ConversationSession, SessionStore
from app.services.synthesis.context_builder import ContextBuilder
from app.services.synthesis.prompt_config import get_prompt_config
from app.services.synthesis.prompts import SYSTEM_INSTRUCTIONS, build_rag_user_message
from app.services.vector.models import SearchFilter

router = APIRouter()
logger = logging.getLogger("app.api.chat")

# How many prior conversation turns (user+assistant pairs) to send to the LLM.
# 10 turns = 20 messages.  Older turns are in the session but not in the prompt.
_MAX_HISTORY_TURNS = 10

_PLAIN_SYSTEM = (
    "You are a helpful AI assistant for a personal knowledge base. "
    "Answer questions based on the user's notes and conversation history. "
    "If you are unsure, say so clearly rather than fabricating information."
)

_FALLBACK_ANSWER = (
    "I couldn't find any relevant information in your notes for this question. "
    "Try rephrasing, lowering the score threshold, or checking that the vault "
    "has been indexed."
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sse(event: StreamEvent) -> bytes:
    """Serialize a StreamEvent to SSE wire format."""
    return f"data: {json.dumps(event.model_dump())}\n\n".encode()


def _build_plain_messages(
    session: ConversationSession,
    current_question: str,
) -> list[LLMMessage]:
    """System + recent history + current user turn."""
    msgs: list[LLMMessage] = [LLMMessage(role="system", content=_PLAIN_SYSTEM)]
    history = session.messages[:-1]  # exclude the current user msg (just added)
    for m in history[-(  _MAX_HISTORY_TURNS * 2) :]:
        msgs.append(LLMMessage(role=m.role, content=m.content))  # type: ignore[arg-type]
    msgs.append(LLMMessage(role="user", content=current_question))
    return msgs


def _build_rag_messages(
    session: ConversationSession,
    context_str: str,
    question: str,
) -> list[LLMMessage]:
    """System instructions + recent history + context-injected user turn.

    The context is injected only into the CURRENT user turn, not into history.
    Earlier turns already contain the model's answers, so injecting context
    there would confuse the model about which excerpts belong to which turn.
    """
    msgs: list[LLMMessage] = [LLMMessage(role="system", content=SYSTEM_INSTRUCTIONS)]
    history = session.messages[:-1]  # exclude current user msg
    for m in history[-(_MAX_HISTORY_TURNS * 2) :]:
        msgs.append(LLMMessage(role=m.role, content=m.content))  # type: ignore[arg-type]
    user_content = build_rag_user_message(context_str, question)
    msgs.append(LLMMessage(role="user", content=user_content))
    return msgs


# ── POST /chat — blocking plain chat ─────────────────────────────────────────

@router.post("", response_model=ChatResponse, summary="Blocking plain chat with session memory")
async def chat(
    request: ChatRequest,
    llm: LLMDep,
    sessions: SessionDep,
) -> ChatResponse:
    """Full-response plain chat.

    Accepts conversation history in `messages` (client-provided) OR via
    `session_id` (server-maintained).  When both are present, the session
    history is used — it takes priority.
    """
    question = request.messages[-1].content
    session = sessions.get_or_create(request.session_id)
    sessions.add_message(session.session_id, "user", question)

    llm_request = ChatCompletionRequest(
        model=llm.chat_model,  # type: ignore[attr-defined]
        messages=_build_plain_messages(session, question),
        options=LLMOptions(),
    )
    completion = await llm.chat(llm_request)
    sessions.add_message(session.session_id, "assistant", completion.content)

    logger.info(
        "Chat completed",
        extra={
            "session_id": session.session_id,
            "model": completion.model,
            "prompt_tokens": completion.prompt_tokens,
            "completion_tokens": completion.completion_tokens,
            "duration_ms": completion.total_duration_ms,
        },
    )
    return ChatResponse(
        content=completion.content,
        sources=[],
        session_id=session.session_id,
    )


# ── POST /chat/stream — streaming plain chat ──────────────────────────────────

@router.post(
    "/stream",
    summary="Streaming plain chat (SSE)",
    description=(
        "Server-Sent Events stream. Events:\n\n"
        "- `{\"type\": \"delta\", \"delta\": \"token\", \"done\": false}` — next token\n"
        "- `{\"type\": \"done\", \"done\": true, \"session_id\": \"...\"}` — stream finished\n"
        "- `{\"type\": \"error\", \"error\": \"...\", \"done\": true}` — fatal error\n\n"
        "Connect with `EventSource` or `fetch` + `ReadableStream`."
    ),
    response_class=StreamingResponse,
)
async def chat_stream(
    request: Request,
    body: ChatRequest,
    llm: LLMDep,
    sessions: SessionDep,
) -> StreamingResponse:
    """Streaming plain chat — yields tokens as Ollama generates them."""
    question = body.messages[-1].content
    session = sessions.get_or_create(body.session_id)
    sessions.add_message(session.session_id, "user", question)

    llm_request = ChatCompletionRequest(
        model=llm.chat_model,  # type: ignore[attr-defined]
        messages=_build_plain_messages(session, question),
        options=LLMOptions(),
    )

    async def _generate() -> AsyncGenerator[bytes, None]:
        accumulated: list[str] = []
        try:
            stream = await llm.chat_stream(llm_request)
            async for delta in stream:
                if await request.is_disconnected():
                    logger.info("Client disconnected mid-stream", extra={"session_id": session.session_id})
                    return
                yield _sse(StreamEvent(type=StreamEventType.DELTA, delta=delta.content, done=delta.done))
                if delta.content:
                    accumulated.append(delta.content)
                if delta.done:
                    break
        except Exception as exc:
            logger.error("Stream error", extra={"error": str(exc), "session_id": session.session_id})
            yield _sse(StreamEvent(type=StreamEventType.ERROR, error=str(exc), done=True))
            return

        full_answer = "".join(accumulated)
        if full_answer:
            sessions.add_message(session.session_id, "assistant", full_answer)

        yield _sse(StreamEvent(
            type=StreamEventType.DONE,
            done=True,
            session_id=session.session_id,
        ))
        logger.info("Stream complete", extra={"session_id": session.session_id, "chars": len(full_answer)})

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── POST /chat/rag — blocking RAG chat ───────────────────────────────────────

@router.post(
    "/rag",
    response_model=RagChatResponse,
    summary="Blocking RAG chat — answers grounded in vault notes",
)
async def rag_chat(
    request: RagChatRequest,
    retrieval: RetrievalDep,
    synthesizer: SynthesisDep,
    sessions: SessionDep,
) -> RagChatResponse:
    """Retrieval-augmented chat (blocking).

    1. Embeds the last user message and retrieves matching chunks from Qdrant.
    2. Passes the retrieved chunks to ContextBuilder + LlamaIndex synthesizer.
    3. Stores the turn in the session.
    4. Returns the answer with source attribution and latency fields.
    """
    question = request.messages[-1].content
    session = sessions.get_or_create(request.session_id)
    sessions.add_message(session.session_id, "user", question)

    filters: SearchFilter | None = None
    if request.tags or request.note_path:
        filters = SearchFilter(tags=request.tags or [], note_path=request.note_path)

    retrieval_result = await retrieval.retrieve(
        RetrievalQuery(
            text=question,
            top_k=request.top_k,
            score_threshold=request.score_threshold,
            filters=filters,
            deduplicate=request.deduplicate,
        )
    )

    synthesis_result = await synthesizer.synthesize(question, retrieval_result.chunks)
    sessions.add_message(session.session_id, "assistant", synthesis_result.answer)

    sources = [
        NoteSource(
            note_title=c.note_title,
            note_path=c.note_path,
            excerpt=c.chunk_text[:300],
            score=c.score,
        )
        for c in synthesis_result.source_chunks
    ]

    logger.info(
        "RAG chat complete",
        extra={
            "session_id": session.session_id,
            "question": question[:120],
            "sources": len(sources),
            "retrieval_ms": retrieval_result.latency_ms,
            "synthesis_ms": synthesis_result.latency_ms,
        },
    )

    return RagChatResponse(
        content=synthesis_result.answer,
        sources=sources,
        session_id=session.session_id,
        retrieval_latency_ms=retrieval_result.latency_ms,
        synthesis_latency_ms=synthesis_result.latency_ms,
        total_candidates=retrieval_result.total_candidates,
        deduplicated_count=retrieval_result.deduplicated_count,
        filters_applied=retrieval_result.filters_applied,
    )


# ── POST /chat/rag/stream — streaming RAG chat ────────────────────────────────

@router.post(
    "/rag/stream",
    summary="Streaming RAG chat (SSE)",
    description=(
        "Server-Sent Events stream. Events in order:\n\n"
        "1. `{\"type\": \"retrieval\", \"sources\": [...], \"candidate_count\": N}` "
        "— emitted right after vector search, before generation starts.\n"
        "2. `{\"type\": \"delta\", \"delta\": \"token\", \"done\": false}` "
        "— one per token chunk.\n"
        "3. `{\"type\": \"done\", \"done\": true, \"session_id\": \"...\", \"sources\": [...]}` "
        "— terminal; stream is complete.\n"
        "4. `{\"type\": \"error\", \"error\": \"...\", \"done\": true}` "
        "— replaces done on unrecoverable failure.\n\n"
        "Connect with `fetch` + `ReadableStream` (EventSource doesn't support POST)."
    ),
    response_class=StreamingResponse,
)
async def rag_stream(
    request: Request,
    body: RagChatRequest,
    llm: LLMDep,
    retrieval: RetrievalDep,
    sessions: SessionDep,
) -> StreamingResponse:
    """Streaming RAG chat.

    Bypasses LlamaIndex for the generation step — we assemble the prompt
    ourselves (via build_rag_user_message) and call llm.chat_stream() directly.
    This gives token-by-token streaming while keeping the same citation format
    and anti-hallucination constraints as the blocking RAG path.
    """
    question = body.messages[-1].content
    session = sessions.get_or_create(body.session_id)
    sessions.add_message(session.session_id, "user", question)

    filters: SearchFilter | None = None
    if body.tags or body.note_path:
        filters = SearchFilter(tags=body.tags or [], note_path=body.note_path)

    config = get_prompt_config(settings.ollama_chat_model)
    context_builder = ContextBuilder(max_context_tokens=config.context_budget)

    async def _generate() -> AsyncGenerator[bytes, None]:
        # ── Stage 1: Retrieve ──────────────────────────────────────────────────
        try:
            retrieval_result = await retrieval.retrieve(
                RetrievalQuery(
                    text=question,
                    top_k=body.top_k,
                    score_threshold=body.score_threshold,
                    filters=filters,
                    deduplicate=body.deduplicate,
                )
            )
        except Exception as exc:
            logger.error("Retrieval failed", extra={"error": str(exc), "session_id": session.session_id})
            yield _sse(StreamEvent(type=StreamEventType.ERROR, error="Retrieval failed: " + str(exc), done=True))
            return

        sources = [
            NoteSource(
                note_title=c.note_title,
                note_path=c.note_path,
                excerpt=c.chunk_text[:300],
                score=c.score,
            )
            for c in retrieval_result.chunks
        ]

        # ── Stage 2: Emit retrieval event ─────────────────────────────────────
        # Frontend can render source cards immediately while the LLM warms up.
        yield _sse(StreamEvent(
            type=StreamEventType.RETRIEVAL,
            sources=sources,
            candidate_count=retrieval_result.total_candidates,
        ))

        if await request.is_disconnected():
            return

        # ── Stage 3: Handle empty context ─────────────────────────────────────
        if not retrieval_result.chunks:
            sessions.add_message(session.session_id, "assistant", _FALLBACK_ANSWER)
            yield _sse(StreamEvent(type=StreamEventType.DELTA, delta=_FALLBACK_ANSWER, done=False))
            yield _sse(StreamEvent(
                type=StreamEventType.DONE,
                done=True,
                session_id=session.session_id,
                sources=[],
            ))
            return

        # ── Stage 4: Build context + prompt ───────────────────────────────────
        built = context_builder.build(retrieval_result.chunks)

        logger.info(
            "RAG stream: context built",
            extra={
                "session_id": session.session_id,
                "chunks_in": len(retrieval_result.chunks),
                "chunks_used": len(built.included_chunks),
                "context_tokens": built.total_tokens,
                "context_truncated": built.was_truncated,
            },
        )

        llm_messages = _build_rag_messages(session, built.context_str, question)
        llm_request = ChatCompletionRequest(
            model=llm.chat_model,  # type: ignore[attr-defined]
            messages=llm_messages,
            options=LLMOptions(),
        )

        # ── Stage 5: Stream tokens ─────────────────────────────────────────────
        accumulated: list[str] = []
        try:
            stream = await llm.chat_stream(llm_request)
            async for delta in stream:
                if await request.is_disconnected():
                    logger.info(
                        "Client disconnected mid RAG stream",
                        extra={"session_id": session.session_id},
                    )
                    return
                yield _sse(StreamEvent(
                    type=StreamEventType.DELTA,
                    delta=delta.content,
                    done=delta.done,
                ))
                if delta.content:
                    accumulated.append(delta.content)
                if delta.done:
                    break
        except Exception as exc:
            logger.error("LLM stream error", extra={"error": str(exc), "session_id": session.session_id})
            yield _sse(StreamEvent(type=StreamEventType.ERROR, error=str(exc), done=True))
            return

        # ── Stage 6: Persist and finalise ─────────────────────────────────────
        full_answer = "".join(accumulated)
        if full_answer:
            sessions.add_message(session.session_id, "assistant", full_answer)

        # Sources in done event reference only included chunks (not over-fetched ones)
        included_sources = [
            NoteSource(
                note_title=c.note_title,
                note_path=c.note_path,
                excerpt=c.chunk_text[:300],
                score=c.score,
            )
            for c in built.included_chunks
        ]

        yield _sse(StreamEvent(
            type=StreamEventType.DONE,
            done=True,
            session_id=session.session_id,
            sources=included_sources,
        ))

        logger.info(
            "RAG stream complete",
            extra={
                "session_id": session.session_id,
                "answer_chars": len(full_answer),
                "sources": len(included_sources),
            },
        )

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── GET /chat/sessions/{session_id} — fetch history ──────────────────────────

@router.get(
    "/sessions/{session_id}",
    response_model=ConversationHistory,
    summary="Get conversation history for a session",
)
async def get_session(
    session_id: str,
    sessions: SessionDep,
) -> ConversationHistory:
    """Return the full message history for a session.

    Returns 404 if the session does not exist or has expired.
    """
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found or expired.",
        )
    return ConversationHistory(
        session_id=session.session_id,
        messages=[
            SessionMessageOut(role=m.role, content=m.content, timestamp=m.timestamp)
            for m in session.messages
        ],
        created_at=session.created_at,
        last_active=session.last_active,
    )


# ── DELETE /chat/sessions/{session_id} — clear session ───────────────────────

@router.delete(
    "/sessions/{session_id}",
    response_model=SessionInfo,
    summary="Delete a session and its history",
)
async def delete_session(
    session_id: str,
    sessions: SessionDep,
) -> SessionInfo:
    """Delete a session.  Returns the final state before deletion.

    Returns 404 if the session does not exist.
    """
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found or expired.",
        )
    info = SessionInfo(
        session_id=session.session_id,
        message_count=len(session.messages),
        created_at=session.created_at,
        last_active=session.last_active,
    )
    sessions.delete(session_id)
    logger.info("Session deleted", extra={"session_id": session_id})
    return info
