"""Token estimation and budget enforcement utilities.

No tokenizer is available at inference time — Ollama doesn't expose a
token-counting endpoint and pulling in a tokenizer dependency (tiktoken,
sentencepiece) would couple us to a specific model family.

We use a character-based heuristic: ~4 characters per token.
This is accurate for English prose and conservative for code (fewer chars
per token), so context budgets will be slightly under-utilised — a safe
default for hallucination-reduction purposes.
"""


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in a string via character count.

    Rule: 4 chars ≈ 1 token (good for English prose; conservative for code).
    Returns 0 for empty strings, at least 1 for any non-empty string.
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


def truncate_to_token_budget(text: str, max_tokens: int) -> tuple[str, bool]:
    """Truncate *text* so that estimate_tokens(result) <= max_tokens.

    Snaps to the last word boundary to avoid cutting mid-word.
    Appends " …" to the truncated result so callers can signal that content
    was omitted.

    Returns:
        (text, False)              if no truncation was needed.
        (truncated_text + " …", True)  if truncation occurred.
    """
    if estimate_tokens(text) <= max_tokens:
        return text, False

    char_limit = max_tokens * 4
    truncated = text[:char_limit]

    # Snap to last word boundary (only if there is a reasonable boundary)
    last_space = truncated.rfind(" ")
    if last_space > char_limit // 2:
        truncated = truncated[:last_space]

    return truncated.rstrip() + " …", True
