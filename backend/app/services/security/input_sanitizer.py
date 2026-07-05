"""Input sanitizer — normalises text before any processing.

Why sanitise inputs?
--------------------
1. Null bytes and control characters can bypass regex pattern matching and
   cause unexpected behaviour in JSON serialisers and log formatters.

2. Unicode lookalike attacks: a homoglyph substitution (e.g. Cyrillic 'а'
   for Latin 'a') can bypass keyword-based injection patterns. NFKC
   normalisation collapses these into their canonical ASCII forms before
   the injection detector runs.

3. Oversized inputs are a denial-of-service vector: embedding a 100 kB
   message would trigger a large Ollama embed call and a slow generation.
   Hard limits prevent this.

Order of operations
-------------------
1. Unicode NFKC normalisation  (prevents lookalike bypasses)
2. Control-character stripping  (keeps \t, \n, \r; strips everything else)
3. Leading/trailing whitespace strip
4. Length truncation            (last — so we truncate clean text)
"""

import re
import unicodedata
from dataclasses import dataclass

# Printable control characters to STRIP.
# \t (0x09), \n (0x0a), \r (0x0d) are kept — they appear in normal vault text.
# Everything else in 0x00–0x1f and 0x7f is stripped.
_STRIP_CONTROLS = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]")

MAX_QUERY_LENGTH: int = 500    # search endpoint query param
MAX_MESSAGE_LENGTH: int = 4_000  # chat message body


@dataclass
class SanitizedInput:
    text: str
    was_truncated: bool
    had_control_chars: bool


def sanitize(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> SanitizedInput:
    """Sanitise *text* for use in downstream processing.

    Returns a SanitizedInput with the cleaned text and flags describing
    what was changed so callers can log anomalies.
    """
    # 1. NFKC normalisation — maps homoglyphs / compatibility forms to canonical
    normalised = unicodedata.normalize("NFKC", text)

    # 2. Strip dangerous control characters
    had_control = bool(_STRIP_CONTROLS.search(normalised))
    cleaned = _STRIP_CONTROLS.sub("", normalised)

    # 3. Strip leading/trailing whitespace
    cleaned = cleaned.strip()

    # 4. Length enforcement
    was_truncated = len(cleaned) > max_length
    if was_truncated:
        cleaned = cleaned[:max_length]

    return SanitizedInput(
        text=cleaned,
        was_truncated=was_truncated,
        had_control_chars=had_control,
    )
