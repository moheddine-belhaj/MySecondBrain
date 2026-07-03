# Task 13 — Security Layer

## What Was Built

A defence-in-depth security layer for the RAG API covering prompt injection detection, indirect injection in retrieved content, input sanitisation, output sanitisation, per-IP rate limiting, retrieval isolation, and a separate structured security audit log.

---

## New Files

| File | Role |
|---|---|
| `app/services/security/injection_detector.py` | Regex-based prompt injection scanner for queries and chunk text |
| `app/services/security/input_sanitizer.py` | Unicode normalisation, control-char stripping, length enforcement |
| `app/services/security/output_sanitizer.py` | System-prompt leakage detection in LLM responses |
| `app/services/security/rate_limiter.py` | Token-bucket per-IP rate limiter |
| `app/services/security/audit_logger.py` | Structured security event logger (`security.audit`) |
| `app/services/security/guard.py` | `SecurityGuard` — per-request orchestrator injected via Depends |
| `app/services/security/__init__.py` | Package exports |
| `tests/services/security/test_injection_detector.py` | 37 tests |
| `tests/services/security/test_input_sanitizer.py` | 15 tests |
| `tests/services/security/test_output_sanitizer.py` | 13 tests |
| `tests/services/security/test_rate_limiter.py` | 13 tests |

## Modified Files

| File | Change |
|---|---|
| `app/exceptions.py` | Added `RateLimitError` (429), `PromptInjectionError` (400) |
| `app/dependencies.py` | Added `get_security_guard`, `chat_rate_limit`, `ingest_rate_limit`, type aliases |
| `app/main.py` | Initialise `chat_rate_limiter` + `ingest_rate_limiter` on `app.state` |
| `app/logging_config.py` | Configure `security.audit` logger |
| `app/api/v1/endpoints/chat.py` | Apply `SecurityGuardDep` + `ChatRateLimitDep` to all chat endpoints |
| `app/api/v1/endpoints/search.py` | Apply guard + rate limit; input-sanitise query param |
| `app/api/v1/endpoints/ingest.py` | Apply `IngestRateLimitDep` |
| `app/models/search.py` | Removed `chunk_id` from public `RetrievedChunkResponse` |

**Test count: 323 → 401 (+78)**

---

## Threat Model

This is a **local-first, single-user** RAG system. That changes the threat model significantly compared to a multi-tenant SaaS product.

| Threat | Likelihood | Impact | Handled? |
|---|---|---|---|
| **Indirect prompt injection** (malicious note in vault) | Medium | High — hijacks LLM output | ✅ Chunk scanning |
| **Direct prompt injection** (malicious query) | Low (user is owner) | Medium | ✅ Query scanning |
| **System prompt leakage** (jailbreak reveals SYSTEM_INSTRUCTIONS) | Low | Low (it's your own system) | ✅ Output sanitiser |
| **Ollama DoS** via rapid requests | Low-Medium | High (CPU-bound) | ✅ Rate limiter |
| **Embedding DoS** via oversized input | Low | Medium | ✅ Input length cap |
| **Internal ID exposure** (vector DB keys) | Low | Low | ✅ Removed from API |
| **XSS via LLM output** | Low (local app) | Low-Medium | Partial (output sanitiser removes HTML-adjacent patterns) |
| **Authentication bypass** | N/A | N/A | N/A — no auth (single user) |
| **SQL injection** | N/A | N/A | N/A — no SQL |

---

## Architecture

### Request Security Pipeline

```
Client Request
      │
      ▼
ChatRateLimitDep / IngestRateLimitDep   ← HTTP 429 if bucket exhausted
      │
      ▼
guard.validate_query(text)              ← sanitise + injection detect
      │   HIGH risk  → HTTP 400 "Query contains disallowed content."
      │   MEDIUM/LOW → sanitised text continues + audit log
      ▼
Endpoint handler (retrieval / synthesis)
      │
      ▼
guard.sanitize_chunks(chunks)           ← scan vault content for indirect injection
      │   Each chunk: replace injection patterns with [FILTERED]
      ▼
LLM generation
      │
      ▼
guard.sanitize_output(answer)           ← strip system-prompt leakage
      │
      ▼
Response
```

### SecurityGuard (per-request)

`SecurityGuard` is created by `get_security_guard()` FastAPI dependency. It holds the `request_id` so every audit log entry is correlatable with the request log:

```python
async def get_security_guard(request: Request) -> SecurityGuard:
    request_id = getattr(request.state, "request_id", None)
    return SecurityGuard(request_id=request_id)
```

Endpoints receive it as `guard: SecurityGuardDep` and call:

```python
question = guard.validate_query(body.messages[-1].content, session_id=session.session_id)
safe_chunks = guard.sanitize_chunks(retrieval_result.chunks, session_id=session.session_id)
answer = guard.sanitize_output(synthesis_result.answer, session_id=session.session_id)
```

---

## Components

### 1. Injection Detector (`injection_detector.py`)

**Two scan contexts:**
- `context="query"` — user-provided query text
- `context="chunk"` — retrieved vault chunk text (adds embedded-instruction patterns)

**Three risk tiers:**

| Level | Trigger | Action |
|---|---|---|
| `high` | Any high-risk pattern matched | HTTP 400, audit log |
| `medium` | Any medium-risk pattern, OR 2+ low-risk | Pass sanitised text, audit log |
| `low` | 1 low-risk pattern | Pass original text, audit log |
| `none` | No patterns | Pass through (no log) |

**HIGH patterns** (almost never appear in legitimate queries):
- `jailbreak`, `DAN` / `do anything now`
- `dump memory/context/state/config`
- `reveal your (system) prompt`

**MEDIUM patterns** (suspicious but rare in legitimate use):
- `ignore (all/previous/your) instructions`
- `forget/override/bypass your instructions`
- `from now on you are/ignore/pretend`
- `developer mode/override`
- `act as an (evil/uncensored/unfiltered) assistant`
- `pretend you have no restrictions`

**LOW patterns** (logged only, not replaced — high false-positive risk):
- `system prompt` (appears in tech discussions)
- `ignore above` (appears in note summaries)
- `hidden instructions/config`

**CHUNK_EXTRA patterns** (chunk context only — embedded LLM instruction markers):
- `## New instructions:` (markdown header injection)
- `[INST]` (Llama instruction tag)
- `<|system|>` / `<|im_start|> system` (chat template tags)
- `<instructions>` (XML tag injection)

**Sanitisation:** HIGH and MEDIUM matched spans are replaced with `[FILTERED]` in the text passed downstream. The surrounding content is preserved — a 1 000-word note with one injected sentence still provides valid context.

### 2. Input Sanitiser (`input_sanitizer.py`)

Applied before injection detection, in this order:

1. **NFKC normalisation** — collapses Unicode homoglyphs (Cyrillic 'а' → ASCII 'a') that would otherwise bypass regex pattern matching
2. **Control-char stripping** — removes `\x00–\x08`, `\x0b`, `\x0c`, `\x0e–\x1f`, `\x7f`. Preserves `\t`, `\n`, `\r` (normal in vault text)
3. **Whitespace trim** — leading/trailing
4. **Length enforcement:**
   - Chat messages: 4 000 chars max
   - Search queries: 500 chars max

### 3. Output Sanitiser (`output_sanitizer.py`)

Scans LLM responses for verbatim phrases from `SYSTEM_INSTRUCTIONS`. If found:
- Replaces the span with `[FILTERED: system information]`
- Sets `was_sanitized=True` → audit log event emitted

Protected phrases (specific enough to avoid false positives):
- `"You are a precise AI assistant for a personal Obsidian knowledge base"`
- `"Rules — follow every rule without exception"`
- `"Answer using ONLY the note excerpts provided"`
- `SYSTEM_INSTRUCTIONS` (the constant name)
- `"my instructions are/say/include"` (self-referential disclosure)
- `"I was instructed to"` (passive disclosure)

### 4. Rate Limiter (`rate_limiter.py`)

Token-bucket algorithm. Two limiters on `app.state`:

| Limiter | Rate | Burst | Endpoint |
|---|---|---|---|
| `chat_rate_limiter` | 30 req/min | 10 | All `/chat/*` and `/search` |
| `ingest_rate_limiter` | 5 req/min | 2 | `/ingest` |

Key = client IP from `X-Forwarded-For` (first hop) or `request.client.host`.

**Burst allowance**: a client that has been idle can fire `burst` requests instantly. This prevents false positives when the UI loads and sends several requests simultaneously.

**Refill**: tokens accumulate at `rpm / 60` per second while the client is idle, capped at `burst`.

When a bucket is exhausted → `RateLimitError` → HTTP 429. The audit logger records the IP, endpoint, and request ID.

### 5. Audit Logger (`audit_logger.py`)

Separate Python logger: `security.audit` (configured alongside `app.*` in `logging_config.py`).

Four event types:

| Event | Trigger | Level |
|---|---|---|
| `prompt_injection_detected` | Injection pattern found in query or chunk | WARNING |
| `rate_limit_exceeded` | Token bucket exhausted | WARNING |
| `output_sanitized` | Leakage pattern found in LLM response | WARNING |
| `input_truncated` | Input exceeded max length | INFO |

Each event includes: `event` (type key), `context`, `risk_level`, `pattern_count`, `session_id`, `request_id`, `ts` (unix timestamp).

Text content is **never logged in full** — only a 50-char preview (`text_preview[:50]`). This prevents logs from becoming a secondary exfiltration vector.

### 6. Retrieval Isolation

**`chunk_id` removed from search response.** `chunk_id` is an internal SHA-256 hash used as the Qdrant vector point key. Exposing it:
- Reveals the internal keying scheme
- Allows correlating responses across requests
- Serves no user-facing purpose (clients identify chunks by `note_path + chunk_index`)

Clients who previously used `chunk_id` can substitute `(note_path, chunk_index)` as a unique identifier within a response set.

`note_id` (SHA-256 of note content) was never in the public API — it's only in internal `RetrievedChunk` dataclass.

---

## Security Decisions

### Why pattern-based detection (not ML)?

- No external model dependency at query time
- Zero cold-start latency
- No network calls
- Fully auditable — the exact patterns are in the code
- Easy to add/tune patterns as new attack vectors emerge

The downside is higher false-negative rate against novel attacks, but for a personal system where the attack surface is narrow, this tradeoff is correct.

### Why warn-and-sanitise for LOW/MEDIUM, not block?

The user is the only person querying the system. Blocking their own query for a LOW-risk signal (e.g., asking "what is a system prompt?") would create friction with no security benefit. MEDIUM signals are sanitised before reaching the LLM — the injection attempt is neutralised even though the request proceeds.

**Only HIGH risk is blocked outright** (HTTP 400). HIGH patterns are those that have no legitimate use in a RAG query (e.g., `jailbreak`, `dump memory`).

### Why in-memory rate limiting (not Redis)?

Redis adds operational complexity. For a local-first single-user system, the rate limiter's dict will contain exactly one key (127.0.0.1). In-memory is faster, simpler, and correct. The downside — state is lost on server restart — is irrelevant for a personal tool.

### Why output sanitisation instead of no-output-logging?

Output sanitisation is a last-resort catch for jailbreaks that bypassed the input checks. It doesn't prevent the jailbreak from succeeding (the model already generated the response) — it prevents the leaked content from reaching the client, and it generates an audit event so you know the injection defences were tested.

---

## Tests

| File | Tests | What's covered |
|---|---|---|
| `test_injection_detector.py` | 37 | HIGH/MEDIUM/LOW/none risk levels, case-insensitivity, sanitisation, chunk context |
| `test_input_sanitizer.py` | 15 | Unicode normalisation, control chars, truncation, length constants |
| `test_output_sanitizer.py` | 13 | Leakage phrase detection, placeholder insertion, clean output unchanged |
| `test_rate_limiter.py` | 13 | Burst allowance, exhaustion, refill, reset, per-key isolation |

---

## Manual Configuration

No `.env` changes required. All security limits are configured in `app/main.py` lifespan and `app/dependencies.py`.

### Adjust rate limits

In `app/main.py`:

```python
app.state.chat_rate_limiter = RateLimiter(
    requests_per_minute=30,  # ← change this
    burst=10,                # ← and this
)
app.state.ingest_rate_limiter = RateLimiter(
    requests_per_minute=5,
    burst=2,
)
```

### Adjust input length limits

In `app/services/security/input_sanitizer.py`:

```python
MAX_QUERY_LENGTH: int = 500     # search endpoint
MAX_MESSAGE_LENGTH: int = 4_000  # chat message body
```

### Add a new injection pattern

Open `app/services/security/injection_detector.py` and add to the appropriate list:

```python
_HIGH: list[tuple[str, re.Pattern[str]]] = [
    ...
    ("my_new_pattern", re.compile(r"\bmy pattern here\b", _F)),
]
```

Rule: `_HIGH` → block on match. `_MEDIUM` → sanitise + log. `_LOW` → log only. `_CHUNK_EXTRA` → chunk text only.

### Add a new output leakage pattern

Open `app/services/security/output_sanitizer.py`:

```python
_LEAKAGE_PATTERNS: list[re.Pattern[str]] = [
    ...
    re.compile(r"my new phrase to protect", _F),
]
```

Only add phrases that are specific enough to avoid false positives in normal RAG answers.

---

## No Manual Steps Required

All security features are activated automatically on server startup. No environment variables, configuration files, or database migrations are needed.
