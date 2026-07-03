"""Output sanitiser — prevents system prompt leakage in LLM responses.

Threat being defended against
------------------------------
A successful jailbreak (or a cleverly-worded RAG-retrieved instruction) may
cause the LLM to include verbatim content from SYSTEM_INSTRUCTIONS in its
response. For a personal system this is more of an embarrassment than a
critical breach, but it indicates the anti-hallucination constraints were
bypassed and the response should not be trusted.

Detection strategy
------------------
Match verbatim phrases that only appear in SYSTEM_INSTRUCTIONS.  These are
specific enough (>30 chars each) that they will not appear in ordinary
note-based answers.  We do NOT use the full instruction text to avoid
creating a maintenance burden (the prompt can be edited without updating
this file as long as these key phrases remain stable).

Action
------
- Replace each leaked span with [FILTERED: system information].
- Set was_sanitized=True so the caller can add an audit log entry.
- The surrounding response text is kept — only the leaked spans are removed.
  This preserves any legitimate content in the same response.

What this does NOT do
----------------------
- General content moderation (not our job for a personal RAG).
- Violence/toxicity filtering.
- Factual accuracy checking.
"""

import re
from dataclasses import dataclass, field

_F = re.IGNORECASE

_LEAKAGE_PATTERNS: list[re.Pattern[str]] = [
    # First sentence of SYSTEM_INSTRUCTIONS
    re.compile(r"You are a precise AI assistant for a personal Obsidian knowledge base", _F),
    # Rule-block header
    re.compile(r"Rules\s*[—–-]\s*follow every rule without exception", _F),
    # Rule 1 fragment
    re.compile(r"Answer using ONLY the note excerpts provided", _F),
    # The constant name itself (model naming its instructions)
    re.compile(r"\bSYSTEM_INSTRUCTIONS\b", _F),
    # Self-referential disclosure
    re.compile(r"\bmy\s+(system\s+)?instructions?\s+(are|say|include|were?|is)\b", _F),
    re.compile(r"\bI\s+(was|am|have\s+been)\s+instructed\s+to\b", _F),
]

_PLACEHOLDER = "[FILTERED: system information]"


@dataclass
class SanitizedOutput:
    text: str
    was_sanitized: bool
    matched_patterns: list[str] = field(default_factory=list)


def sanitize_output(text: str) -> SanitizedOutput:
    """Scan LLM *text* for system-prompt leakage and replace leaked spans.

    Returns the sanitised text and metadata indicating whether any
    replacements were made.
    """
    sanitized = text
    matched: list[str] = []

    for pattern in _LEAKAGE_PATTERNS:
        if pattern.search(sanitized):
            matched.append(pattern.pattern)
            sanitized = pattern.sub(_PLACEHOLDER, sanitized)

    return SanitizedOutput(
        text=sanitized,
        was_sanitized=bool(matched),
        matched_patterns=matched,
    )
