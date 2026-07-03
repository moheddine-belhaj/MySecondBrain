"""Chat endpoints — plain and RAG, blocking and streaming.

Security applied at every endpoint
-----------------------------------
1. Rate limit   — ChatRateLimitDep (30 req/min, burst 10 per IP).
2. Input check  — guard.validate_query(): sanitise + injection detect.
                  HIGH risk → HTTP 400. MEDIUM/LOW → sanitised text + audit log.
3. Chunk scan   — guard.sanitize_chunks(): indirect injection in vault content.
4. Output scan  — guard.sanitize_output(): system-prompt leakage detection.

Endpoint map
------------
POST /chat              — Blocking plain chat with session memory
POST /chat/stream       — Streaming plain chat (SSE) with session memory
POST /chat/rag          — Blocking RAG chat (retrieval + synthesis)
POST /chat/rag/stream   — Streaming RAG (SSE): retrieval event → tokens → done
GET  /chat/sessions/{id} — Fetch conversation history
DELETE /chat/sessions/{id} — Clear a session

SSE wire format
---------------
Each event:  data: <JSON>\\n\\n  (StreamEvent schema — see models/chat.py)
"""

import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.config.settings import settings
from app.dependencies import (
    ChatRateLimitDep,
    LLMDep,
    RetrievalDep,
    SecurityGuardDep,
    SessionDep,
    SynthesisDep,
)
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
    return f"data: {json.dumps(event.model_dump())}\n\n".encode()


def _build_plain_messages(
    session: ConversationSession, current_question: str
) -> list[LLMMessage]:
    msgs: list[LLMMessage] = [LLMMessage(role="system", content=_PLAIN_SYSTEM)]
    history = session.messages[:-1]
    for m in history[-(_MAX_HISTORY_TURNS * 2):]:
        msgs.append(LLMMessage(role=m.role, content=m.content))  # type: ignore[arg-type]
    msgs.append(LLMMessage(role="user", content=current_question))
    return msgs


def _build_rag_messages(
    session: ConversationSession, context_str: str, question: str
) -> list[LLMMessage]:
    msgs: list[LLMMessage] = [LLMMessage(role="system", content=SYSTEM_INSTRUCTIONS)]
    history = session.messages[:-1]
    for m in history[-(_MAX_HISTORY_TURNS * 2):]:
        msgs.append(LLMMessage(role=m.role, content=m.content))  # type: ignore[arg-type]
    msgs.append(LLMMessage(role="user", content=build_rag_user_message(context_str, question)))
    return msgs


# ── POST /chat ────────────────────────────────────────────────────────────────

@router.post("", response_model=ChatResponse, summary="Blocking plain chat with session memory")
async def chat(
    request: ChatRequest,
    llm: LLMDep,
    sessions: SessionDep,
    guard: SecurityGuardDep,
    _rl: ChatRateLimitDep,
) -> ChatResponse:
    session = sessions.get_or_create(request.session_id)
    question = guard.validate_query(
        request.messages[-1].content, session_id=session.session_id
    )
    sessions.add_message(session.session_id, "user", question)

    llm_request = ChatCompletionRequest(
        model=llm.chat_model,  # type: ignore[attr-defined]
        messages=_build_plain_messages(session, question),
        options=LLMOptions(),
    )
    completion = await llm.chat(llm_request)
    answer = guard.sanitize_output(completion.content, session_id=session.session_id)
    sessions.add_message(session.session_id, "assistant", answer)

    logger.info(
        "Chat completed",
        extra={
            "session_id": session.session_id,
            "model": completion.model,
            "prompt_tokens": completion.prompt_tokens,
            "completion_tokens": completion.completion_tokens,
        },
    )
    return ChatResponse(content=answer, sources=[], session_id=session.session_id)


# ── POST /chat/stream ─────────────────────────────────────────────────────────

@router.post(
    "/stream",
    summary="Streaming plain chat (SSE)",
    response_class=StreamingResponse,
)
async def chat_stream(
    request: Request,
    body: ChatRequest,
    llm: LLMDep,
    sessions: SessionDep,
    guard: SecurityGuardDep,
    _rl: ChatRateLimitDep,
) -> StreamingResponse:
    session = sessions.get_or_create(body.session_id)
    question = guard.validate_query(
        body.messages[-1].content, session_id=session.session_id
    )
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
                    logger.info("Client disconnected", extra={"session_id": session.session_id})
                    return
                yield _sse(StreamEvent(type=StreamEventType.DELTA, delta=delta.content, done=delta.done))
                if delta.content:
                    accumulated.append(delta.content)
                if delta.done:
                    break
        except Exception as exc:
            logger.error("Stream error", extra={"error": str(exc)})
            yield _sse(StreamEvent(type=StreamEventType.ERROR, error=str(exc), done=True))
            return

        full_answer = guard.sanitize_output("".join(accumulated), session_id=session.session_id)
        if full_answer:
            sessions.add_message(session.session_id, "assistant", full_answer)

        yield _sse(StreamEvent(type=StreamEventType.DONE, done=True, session_id=session.session_id))

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ── POST /chat/rag ────────────────────────────────────────────────────────────

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
    guard: SecurityGuardDep,
    _rl: ChatRateLimitDep,
) -> RagChatResponse:
    session = sessions.get_or_create(request.session_id)
    question = guard.validate_query(
        request.messages[-1].content, session_id=session.session_id
    )
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

    # Scan retrieved chunks for indirect injection before synthesis
    safe_chunks = guard.sanitize_chunks(retrieval_result.chunks, session_id=session.session_id)
    synthesis_result = await synthesizer.synthesize(question, safe_chunks)
    answer = guard.sanitize_output(synthesis_result.answer, session_id=session.session_id)
    sessions.add_message(session.session_id, "assistant", answer)

    sources = [
        NoteSource(note_title=c.note_title, note_path=c.note_path, excerpt=c.chunk_text[:300], score=c.score)
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
        content=answer,
        sources=sources,
        session_id=session.session_id,
        retrieval_latency_ms=retrieval_result.latency_ms,
        synthesis_latency_ms=synthesis_result.latency_ms,
        total_candidates=retrieval_result.total_candidates,
        deduplicated_count=retrieval_result.deduplicated_count,
        filters_applied=retrieval_result.filters_applied,
    )


# ── POST /chat/rag/stream ─────────────────────────────────────────────────────

@router.post(
    "/rag/stream",
    summary="Streaming RAG chat (SSE)",
    response_class=StreamingResponse,
)
async def rag_stream(
    request: Request,
    body: RagChatRequest,
    llm: LLMDep,
    retrieval: RetrievalDep,
    sessions: SessionDep,
    guard: SecurityGuardDep,
    _rl: ChatRateLimitDep,
) -> StreamingResponse:
    session = sessions.get_or_create(body.session_id)
    question = guard.validate_query(
        body.messages[-1].content, session_id=session.session_id
    )
    sessions.add_message(session.session_id, "user", question)

    filters: SearchFilter | None = None
    if body.tags or body.note_path:
        filters = SearchFilter(tags=body.tags or [], note_path=body.note_path)

    config = get_prompt_config(settings.ollama_chat_model)
    context_builder = ContextBuilder(max_context_tokens=config.context_budget)

    async def _generate() -> AsyncGenerator[bytes, None]:
        # Stage 1: retrieve
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
            logger.error("Retrieval failed", extra={"error": str(exc)})
            yield _sse(StreamEvent(type=StreamEventType.ERROR, error="Retrieval failed.", done=True))
            return

        # Stage 2: scan chunks for indirect injection
        safe_chunks = guard.sanitize_chunks(retrieval_result.chunks, session_id=session.session_id)

        sources = [
            NoteSource(note_title=c.note_title, note_path=c.note_path, excerpt=c.chunk_text[:300], score=c.score)
            for c in safe_chunks
        ]
        yield _sse(StreamEvent(
            type=StreamEventType.RETRIEVAL,
            sources=sources,
            candidate_count=retrieval_result.total_candidates,
        ))

        if await request.is_disconnected():
            return

        # Stage 3: handle empty context
        if not safe_chunks:
            sessions.add_message(session.session_id, "assistant", _FALLBACK_ANSWER)
            yield _sse(StreamEvent(type=StreamEventType.DELTA, delta=_FALLBACK_ANSWER, done=False))
            yield _sse(StreamEvent(type=StreamEventType.DONE, done=True, session_id=session.session_id))
            return

        # Stage 4: build context + prompt
        built = context_builder.build(safe_chunks)
        llm_messages = _build_rag_messages(session, built.context_str, question)
        llm_request = ChatCompletionRequest(
            model=llm.chat_model,  # type: ignore[attr-defined]
            messages=llm_messages,
            options=LLMOptions(),
        )

        # Stage 5: stream tokens
        accumulated: list[str] = []
        try:
            stream = await llm.chat_stream(llm_request)
            async for delta in stream:
                if await request.is_disconnected():
                    logger.info("Client disconnected mid RAG stream", extra={"session_id": session.session_id})
                    return
                yield _sse(StreamEvent(type=StreamEventType.DELTA, delta=delta.content, done=delta.done))
                if delta.content:
                    accumulated.append(delta.content)
                if delta.done:
                    break
        except Exception as exc:
            logger.error("LLM stream error", extra={"error": str(exc)})
            yield _sse(StreamEvent(type=StreamEventType.ERROR, error=str(exc), done=True))
            return

        # Stage 6: output sanitisation + session storage
        full_answer = guard.sanitize_output("".join(accumulated), session_id=session.session_id)
        if full_answer:
            sessions.add_message(session.session_id, "assistant", full_answer)

        included_sources = [
            NoteSource(note_title=c.note_title, note_path=c.note_path, excerpt=c.chunk_text[:300], score=c.score)
            for c in built.included_chunks
        ]
        yield _sse(StreamEvent(
            type=StreamEventType.DONE,
            done=True,
            session_id=session.session_id,
            sources=included_sources,
        ))
        logger.info("RAG stream complete", extra={"session_id": session.session_id, "chars": len(full_answer)})

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ── GET /chat/sessions/{session_id} ──────────────────────────────────────────

@router.get("/sessions/{session_id}", response_model=ConversationHistory, summary="Get conversation history")
async def get_session(session_id: str, sessions: SessionDep) -> ConversationHistory:
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session '{session_id}' not found.")
    return ConversationHistory(
        session_id=session.session_id,
        messages=[SessionMessageOut(role=m.role, content=m.content, timestamp=m.timestamp) for m in session.messages],
        created_at=session.created_at,
        last_active=session.last_active,
    )


# ── DELETE /chat/sessions/{session_id} ───────────────────────────────────────

@router.delete("/sessions/{session_id}", response_model=SessionInfo, summary="Delete a session")
async def delete_session(session_id: str, sessions: SessionDep) -> SessionInfo:
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session '{session_id}' not found.")
    info = SessionInfo(
        session_id=session.session_id,
        message_count=len(session.messages),
        created_at=session.created_at,
        last_active=session.last_active,
    )
    sessions.delete(session_id)
    return info
