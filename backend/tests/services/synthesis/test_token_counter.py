"""Unit tests for token_counter utilities."""

import pytest

from app.services.synthesis.token_counter import estimate_tokens, truncate_to_token_budget


class TestEstimateTokens:
    def test_empty_string_returns_zero(self):
        assert estimate_tokens("") == 0

    def test_nonempty_returns_at_least_one(self):
        assert estimate_tokens("hi") >= 1

    def test_400_chars_is_100_tokens(self):
        assert estimate_tokens("a" * 400) == 100

    def test_800_chars_is_200_tokens(self):
        assert estimate_tokens("a" * 800) == 200

    def test_longer_text_has_more_tokens(self):
        assert estimate_tokens("a" * 800) > estimate_tokens("a" * 400)

    def test_single_char_returns_one(self):
        assert estimate_tokens("x") == 1

    def test_four_chars_returns_one(self):
        assert estimate_tokens("abcd") == 1

    def test_eight_chars_returns_two(self):
        assert estimate_tokens("abcdefgh") == 2


class TestTruncateToTokenBudget:
    def test_short_text_not_truncated(self):
        text, truncated = truncate_to_token_budget("hello world", 100)
        assert text == "hello world"
        assert truncated is False

    def test_exact_budget_not_truncated(self):
        text = "a" * 400  # exactly 100 tokens
        result, truncated = truncate_to_token_budget(text, 100)
        assert truncated is False
        assert result == text

    def test_long_text_gets_truncated(self):
        text = "word " * 1000  # ~5 000 chars → ~1 250 tokens
        result, truncated = truncate_to_token_budget(text, 50)
        assert truncated is True
        assert len(result) < len(text)

    def test_truncated_result_ends_with_ellipsis(self):
        text = "word " * 1000
        result, _ = truncate_to_token_budget(text, 50)
        assert result.endswith(" …")

    def test_truncated_result_fits_in_budget(self):
        text = "a " * 2000  # ~4 000 chars, ~1 000 tokens
        result, truncated = truncate_to_token_budget(text, 100)
        assert truncated is True
        # Allow small overshoot from word-boundary snap and ellipsis
        assert estimate_tokens(result) <= 105

    def test_returns_tuple_of_two(self):
        result = truncate_to_token_budget("text", 10)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_zero_budget_produces_ellipsis(self):
        text = "some text here"
        result, truncated = truncate_to_token_budget(text, 0)
        assert truncated is True
