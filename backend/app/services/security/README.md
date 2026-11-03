# services/security

Defenses for prompt injection and abuse. Endpoints use `SecurityGuard` only, never the sub-modules directly.

- `guard.py`: `SecurityGuard`, created per request (carries the request ID for audit logs).
  - `validate_query()`: sanitize and detect injection in the user input
  - `sanitize_chunks()`: scan retrieved notes for indirect injection
  - `sanitize_output()`: scan the LLM output for system-prompt leakage
- `input_sanitizer.py`: normalizes and truncates text (`MAX_QUERY_LENGTH` 500, `MAX_MESSAGE_LENGTH` 4000).
- `injection_detector.py`: regex patterns that produce a risk level (low, medium, high).
- `output_sanitizer.py`: replaces leaked prompt spans.
- `rate_limiter.py`: token bucket keyed by client (IP). Chat is 30 req/min with burst 10; ingest is 5 req/min with burst 2.
- `audit_logger.py`: structured log events for each security action.

## Blocking policy
| Risk | Action |
|------|--------|
| high | Reject with `PromptInjectionError` (HTTP 400) |
| medium | Use the sanitized text and log an audit event |
| low | Use the original text and log an audit event |
