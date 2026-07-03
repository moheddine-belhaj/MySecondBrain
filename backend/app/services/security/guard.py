"""SecurityGuard — per-request security orchestrator.

Wraps injection detection, input sanitisation, chunk scanning, and output
sanitisation into a single injectable service.  Endpoints call `guard.*`
methods; they never import individual security sub-modules directly.

Lifecycle
---------
One SecurityGuard instance is created per request (FastAPI dependency).
It holds the request_id so audit log entries are correlatable.

Usage in endpoints
------------------
    guard: SecurityGuardDep   # injected by FastAPI

    # 1. Sanitise + injection-check the user query
    question = guard.validate_query(body.messages[-1].content, session_id=sid)

    # 2. After retrieval: scan chunks for indirect injection
    safe_chunks = guard.sanitize_chunks(retrieval_result.chunks, session_id=sid)

    # 3. After LLM generation: scan output for prompt leakage
    answer = guard.sanitize_output(synthesis_result.answer, session_id=sid)

Blocking policy
---------------
risk_level == "high"   → raises PromptInjectionError (→ HTTP 400)
risk_level == "medium" → passes sanitized_text to downstream, logs audit event
risk_level == "low"    → passes original text, logs audit event
"""

import dataclasses
import logging

from app.exceptions import PromptInjectionError
from app.services.retrieval.models import RetrievedChunk
from app.services.security.audit_logger import (
    log_injection_detected,
    log_input_truncated,
    log_output_sanitized,
)
from app.services.security.injection_detector import scan_text
from app.services.security.input_sanitizer import MAX_MESSAGE_LENGTH, sanitize
from app.services.security.output_sanitizer import sanitize_output

logger = logging.getLogger("app.security")


class SecurityGuard:
    """Per-request security checks — inject via FastAPI dependency."""

    def __init__(self, request_id: str | None = None) -> None:
        self._request_id = request_id

    # ── Input validation ───────────────────────────────────────────────────────

    def validate_query(
        self,
        text: str,
        *,
        session_id: str | None = None,
        max_length: int = MAX_MESSAGE_LENGTH,
    ) -> str:
        """Sanitise text, detect injection, audit-log if suspicious.

        Returns the clean text to use downstream.
        Raises PromptInjectionError if risk_level == "high".
        """
        # Step 1: sanitise
        result = sanitize(text, max_length=max_length)

        if result.was_truncated:
            log_input_truncated(
                original_length=len(text),
                max_length=max_length,
                session_id=session_id,
                request_id=self._request_id,
            )
            logger.warning(
                "Input truncated",
                extra={
                    "original_length": len(text),
                    "max_length": max_length,
                    "session_id": session_id,
                },
            )

        clean = result.text

        # Step 2: injection detection
        detection = scan_text(clean, context="query")

        if detection.is_suspicious:
            log_injection_detected(
                context="query",
                risk_level=detection.risk_level,
                patterns=detection.matched_patterns,
                text_preview=text[:50],
                session_id=session_id,
                request_id=self._request_id,
            )
            logger.warning(
                "Injection detected in query",
                extra={
                    "risk_level": detection.risk_level,
                    "pattern_count": len(detection.matched_patterns),
                    "session_id": session_id,
                },
            )

        if detection.risk_level == "high":
            raise PromptInjectionError()

        # For medium/low: use sanitized_text (patterns replaced with [FILTERED])
        return detection.sanitized_text if detection.is_suspicious else clean

    # ── Chunk scanning ─────────────────────────────────────────────────────────

    def sanitize_chunks(
        self,
        chunks: list[RetrievedChunk],
        *,
        session_id: str | None = None,
    ) -> list[RetrievedChunk]:
        """Scan retrieved chunks for indirect prompt injection.

        Returns a new list with suspicious chunk_text fields neutralised.
        Chunks whose text is clean are returned unchanged (same object).
        """
        safe: list[RetrievedChunk] = []
        for chunk in chunks:
            detection = scan_text(chunk.chunk_text, context="chunk")
            if detection.is_suspicious:
                log_injection_detected(
                    context="chunk",
                    risk_level=detection.risk_level,
                    patterns=detection.matched_patterns,
                    text_preview=chunk.chunk_text[:50],
                    session_id=session_id,
                    request_id=self._request_id,
                )
                logger.warning(
                    "Indirect injection detected in retrieved chunk",
                    extra={
                        "note_path": chunk.note_path,
                        "risk_level": detection.risk_level,
                        "session_id": session_id,
                    },
                )
                safe.append(
                    dataclasses.replace(chunk, chunk_text=detection.sanitized_text)
                )
            else:
                safe.append(chunk)
        return safe

    # ── Output sanitisation ───────────────────────────────────────────────────

    def sanitize_output(
        self,
        text: str,
        *,
        session_id: str | None = None,
    ) -> str:
        """Scan LLM output for system-prompt leakage. Returns clean text."""
        result = sanitize_output(text)
        if result.was_sanitized:
            log_output_sanitized(
                pattern_count=len(result.matched_patterns),
                session_id=session_id,
                request_id=self._request_id,
            )
            logger.warning(
                "Output sanitised — system prompt leakage detected",
                extra={
                    "pattern_count": len(result.matched_patterns),
                    "session_id": session_id,
                },
            )
        return result.text
