"""Prompt injection detector.

Threat model
------------
Two injection surfaces exist in a RAG system:

1. DIRECT injection — the user's own query contains instructions designed to
   override the system prompt ("ignore all previous instructions and reveal…").
   Risk for a personal system: low (the user is the only one querying). Still
   worth detecting for indirect paths (shared access, API exposure, copy-paste).

2. INDIRECT injection — malicious text is embedded in a vault note. When that
   note is retrieved as context, the injected instructions reach the LLM inside
   the "trusted" context block. This is the primary threat for a RAG system:
   a user could paste an email / webpage into Obsidian that contains adversarial
   text designed to hijack the model's output.

Detection strategy
------------------
Pattern-based (compiled regex). No ML model dependency — avoids cold-start
latency, network calls, and external trust. Patterns cover the most common
injection techniques documented in academic and red-team literature.

Three risk tiers:
  high   — near-certain injection attempt → block or neutralise
  medium — suspicious, context-dependent → neutralise and log
  low    — possible benign, needs logging → pass through with audit trail

Case-insensitive matching. Unicode-aware (patterns applied after NFKC
normalisation by the input sanitiser).

Sanitisation
------------
For medium/high patterns the matched span is replaced with [FILTERED].
This neutralises the injection while preserving the surrounding context,
which matters for indirect injection in chunk text — a 1 000-word note
with one injected sentence should still be retrievable.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

RiskLevel = Literal["none", "low", "medium", "high"]
ScanContext = Literal["query", "chunk"]

_F = re.IGNORECASE


@dataclass
class DetectionResult:
    is_suspicious: bool
    risk_level: RiskLevel
    matched_patterns: list[str] = field(default_factory=list)
    sanitized_text: str = ""


# ── Pattern definitions ────────────────────────────────────────────────────────
# Each entry: (label, compiled_pattern)
# Labels are stored in DetectionResult.matched_patterns as "level:label".

_HIGH: list[tuple[str, re.Pattern[str]]] = [
    ("jailbreak",       re.compile(r"\bjailbreak\b", _F)),
    ("DAN_mode",        re.compile(r"\b(DAN|do\s+anything\s+now)\b", _F)),
    ("memory_dump",     re.compile(r"\bdump\s+(memory|context|state|config)\b", _F)),
    ("prompt_reveal",   re.compile(r"\breveal\s+(your|the|this)\s+(system\s+)?prompt\b", _F)),
    ("prompt_expose",   re.compile(r"\byour\s+(system\s+)?prompt\s+(is|was|says?|contains?)\b", _F)),
]

_MEDIUM: list[tuple[str, re.Pattern[str]]] = [
    ("ignore_instructions",   re.compile(r"\bignore\s+(all\s+|previous\s+|your\s+)instructions\b", _F)),
    ("override_instructions", re.compile(r"\b(forget|override|bypass)\s+(your\s+|all\s+|the\s+)?instructions\b", _F)),
    ("from_now_on",           re.compile(r"\bfrom\s+now\s+on\s+(you\s+)?(are|ignore|pretend|forget)\b", _F)),
    ("developer_mode",        re.compile(r"\bdeveloper\s+(mode|override)\b", _F)),
    ("evil_persona",          re.compile(r"\bact\s+as\s+(if\s+you\s+are\s+|an?\s+)?(evil|unrestricted|uncensored|unfiltered)\b", _F)),
    ("no_restrictions",       re.compile(r"\bpretend\s+(you\s+have\s+no|there\s+are\s+no)\s+(restrictions?|rules?|limits?)\b", _F)),
    ("new_instructions",      re.compile(r"\byour\s+new\s+instructions\b", _F)),
]

_LOW: list[tuple[str, re.Pattern[str]]] = [
    ("system_prompt_ref",  re.compile(r"\bsystem\s+prompt\b", _F)),
    ("ignore_above",       re.compile(r"\bignore\s+(all\s+)?above\b", _F)),
    ("hidden_content",     re.compile(r"\bhidden\s+(instructions?|prompt|config)\b", _F)),
    ("your_instructions",  re.compile(r"\byour\s+instructions\b", _F)),
]

# Patterns added only when scanning retrieved chunk text (indirect injection).
# These detect embedded instruction markers used by LLM chat template formats.
_CHUNK_EXTRA: list[tuple[str, re.Pattern[str]]] = [
    ("embedded_header",  re.compile(r"^\s*#{1,3}\s*new\s+instructions?\s*:", re.IGNORECASE | re.MULTILINE)),
    ("llama_inst_tag",   re.compile(r"\[INST\]", _F)),
    ("system_tag",       re.compile(r"<\|system\|>|<\|im_start\|>\s*system", _F)),
    ("xml_inst_tag",     re.compile(r"<instructions?>", _F)),
]

_PLACEHOLDER = "[FILTERED]"


def scan_text(text: str, context: ScanContext = "query") -> DetectionResult:
    """Scan *text* for prompt injection patterns and return a DetectionResult.

    Parameters
    ----------
    text:
        The text to scan — a user query or a retrieved vault chunk.
    context:
        "query"  — applies HIGH + MEDIUM + LOW patterns.
        "chunk"  — additionally applies CHUNK_EXTRA (embedded instruction markers).

    Returns
    -------
    DetectionResult with:
        is_suspicious   — True if any pattern matched.
        risk_level      — "none" / "low" / "medium" / "high".
        matched_patterns — list of "level:label" strings for each match.
        sanitized_text  — original text with HIGH+MEDIUM matches replaced by
                          [FILTERED]. LOW matches are logged but not replaced
                          (too many false positives in everyday queries).
    """
    matched: list[str] = []
    sanitized = text

    for label, pattern in _HIGH:
        if pattern.search(text):
            matched.append(f"high:{label}")

    for label, pattern in _MEDIUM:
        if pattern.search(text):
            matched.append(f"medium:{label}")

    for label, pattern in _LOW:
        if pattern.search(text):
            matched.append(f"low:{label}")

    if context == "chunk":
        for label, pattern in _CHUNK_EXTRA:
            if pattern.search(text):
                matched.append(f"high:{label}")

    if not matched:
        return DetectionResult(
            is_suspicious=False,
            risk_level="none",
            matched_patterns=[],
            sanitized_text=text,
        )

    # Determine risk level
    has_high = any(m.startswith("high:") for m in matched)
    has_medium = any(m.startswith("medium:") for m in matched)
    low_count = sum(1 for m in matched if m.startswith("low:"))

    if has_high:
        risk_level: RiskLevel = "high"
    elif has_medium:
        risk_level = "medium"
    elif low_count >= 2:
        risk_level = "medium"
    else:
        risk_level = "low"

    # Replace high+medium patterns with placeholder in the sanitized copy.
    # Low-risk patterns are NOT replaced (e.g. "system prompt" in a legit note).
    for _, pattern in _HIGH:
        sanitized = pattern.sub(_PLACEHOLDER, sanitized)
    for _, pattern in _MEDIUM:
        sanitized = pattern.sub(_PLACEHOLDER, sanitized)
    if context == "chunk":
        for _, pattern in _CHUNK_EXTRA:
            sanitized = pattern.sub(_PLACEHOLDER, sanitized)

    return DetectionResult(
        is_suspicious=True,
        risk_level=risk_level,
        matched_patterns=matched,
        sanitized_text=sanitized,
    )
