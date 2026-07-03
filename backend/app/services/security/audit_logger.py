"""Security audit logger.

Emits structured security events to the "security.audit" logger, which is
configured separately from the application logger ("app.*") in logging_config.py.

Design decisions
----------------
1. Separate logger name ("security.audit") so security events can be routed
   to a different sink (file, SIEM) without touching application log routing.

2. Structured fields — every event has a fixed set of fields so log aggregators
   can filter/count without text parsing. The "event" field is the primary key.

3. Text previews are capped at 50 chars — enough for a human to recognise
   the pattern, not enough to reconstruct PII or confidential note content.

4. We do NOT log the full message content or matched pattern text. Logging the
   actual injected string would create a secondary exfiltration vector if the
   logs are ever exposed.

5. All events are WARNING level — below ERROR (no alert fatigue for common
   low-risk events) but above INFO (clearly requires human review if frequent).
"""

import logging
import time

_audit = logging.getLogger("security.audit")


def log_injection_detected(
    *,
    context: str,
    risk_level: str,
    patterns: list[str],
    text_preview: str = "",
    session_id: str | None = None,
    request_id: str | None = None,
) -> None:
    """Emitted when the injection detector flags a query or retrieved chunk."""
    _audit.warning(
        "prompt_injection_detected",
        extra={
            "event": "prompt_injection_detected",
            "context": context,
            "risk_level": risk_level,
            "pattern_count": len(patterns),
            "patterns": patterns,
            "text_preview": text_preview[:50],
            "session_id": session_id,
            "request_id": request_id,
            "ts": time.time(),
        },
    )


def log_rate_limit_exceeded(
    *,
    client_ip: str,
    endpoint: str,
    request_id: str | None = None,
) -> None:
    """Emitted when a client exceeds the configured rate limit."""
    _audit.warning(
        "rate_limit_exceeded",
        extra={
            "event": "rate_limit_exceeded",
            "client_ip": client_ip,
            "endpoint": endpoint,
            "request_id": request_id,
            "ts": time.time(),
        },
    )


def log_output_sanitized(
    *,
    pattern_count: int,
    session_id: str | None = None,
    request_id: str | None = None,
) -> None:
    """Emitted when the output sanitiser removes system-prompt leakage."""
    _audit.warning(
        "output_sanitized",
        extra={
            "event": "output_sanitized",
            "pattern_count": pattern_count,
            "session_id": session_id,
            "request_id": request_id,
            "ts": time.time(),
        },
    )


def log_input_truncated(
    *,
    original_length: int,
    max_length: int,
    session_id: str | None = None,
    request_id: str | None = None,
) -> None:
    """Emitted when an oversized input is trimmed to the allowed maximum."""
    _audit.info(
        "input_truncated",
        extra={
            "event": "input_truncated",
            "original_length": original_length,
            "max_length": max_length,
            "session_id": session_id,
            "request_id": request_id,
            "ts": time.time(),
        },
    )
