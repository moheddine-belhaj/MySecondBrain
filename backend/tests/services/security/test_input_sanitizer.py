"""Unit tests for the input sanitiser."""

import pytest

from app.services.security.input_sanitizer import MAX_MESSAGE_LENGTH, MAX_QUERY_LENGTH, sanitize


class TestSanitize:
    def test_clean_text_unchanged(self):
        text = "What is the capital of France?"
        result = sanitize(text)
        assert result.text == text

    def test_leading_whitespace_stripped(self):
        result = sanitize("   hello world")
        assert result.text == "hello world"

    def test_trailing_whitespace_stripped(self):
        result = sanitize("hello world   ")
        assert result.text == "hello world"

    def test_null_bytes_stripped(self):
        result = sanitize("hello\x00world")
        assert "\x00" not in result.text
        assert result.had_control_chars is True

    def test_control_chars_stripped(self):
        result = sanitize("hello\x01\x02world")
        assert "\x01" not in result.text
        assert "\x02" not in result.text

    def test_newlines_preserved(self):
        text = "line one\nline two"
        result = sanitize(text)
        assert "\n" in result.text

    def test_tabs_preserved(self):
        text = "col1\tcol2"
        result = sanitize(text)
        assert "\t" in result.text

    def test_had_control_chars_false_for_clean(self):
        result = sanitize("clean text")
        assert result.had_control_chars is False

    def test_truncation_at_max_length(self):
        text = "a" * (MAX_MESSAGE_LENGTH + 100)
        result = sanitize(text)
        assert len(result.text) == MAX_MESSAGE_LENGTH
        assert result.was_truncated is True

    def test_short_text_not_truncated(self):
        text = "short text"
        result = sanitize(text)
        assert result.was_truncated is False

    def test_exact_max_length_not_truncated(self):
        text = "a" * MAX_MESSAGE_LENGTH
        result = sanitize(text)
        assert result.was_truncated is False

    def test_custom_max_length_respected(self):
        text = "hello world"
        result = sanitize(text, max_length=5)
        assert len(result.text) == 5
        assert result.was_truncated is True

    def test_unicode_normalization(self):
        # Fullwidth latin letters → ASCII via NFKC
        result = sanitize("ｈｅｌｌｏ")  # ｈｅｌｌｏ
        assert result.text == "hello"

    def test_empty_string_returns_empty(self):
        result = sanitize("")
        assert result.text == ""
        assert result.was_truncated is False
        assert result.had_control_chars is False

    def test_query_length_constant_smaller_than_message(self):
        assert MAX_QUERY_LENGTH < MAX_MESSAGE_LENGTH
