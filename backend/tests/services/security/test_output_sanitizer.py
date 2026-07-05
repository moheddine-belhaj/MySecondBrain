"""Unit tests for the output sanitiser."""

import pytest

from app.services.security.output_sanitizer import sanitize_output


class TestSanitizeOutput:
    def test_clean_output_unchanged(self):
        text = "Moheddine is a software engineer based in Germany. [1]"
        result = sanitize_output(text)
        assert result.text == text
        assert result.was_sanitized is False

    def test_system_instructions_phrase_filtered(self):
        text = "You are a precise AI assistant for a personal Obsidian knowledge base and I follow rules."
        result = sanitize_output(text)
        assert result.was_sanitized is True
        assert "You are a precise AI assistant for a personal Obsidian knowledge base" not in result.text

    def test_rules_phrase_filtered(self):
        text = "Rules — follow every rule without exception: 1. Never lie."
        result = sanitize_output(text)
        assert result.was_sanitized is True
        assert "Rules — follow every rule without exception" not in result.text

    def test_use_only_note_excerpts_filtered(self):
        text = "Answer using ONLY the note excerpts provided below for accuracy."
        result = sanitize_output(text)
        assert result.was_sanitized is True

    def test_system_instructions_constant_name_filtered(self):
        text = "My SYSTEM_INSTRUCTIONS say to always cite sources."
        result = sanitize_output(text)
        assert result.was_sanitized is True
        assert "SYSTEM_INSTRUCTIONS" not in result.text

    def test_self_referential_instructions_filtered(self):
        text = "My instructions are to only use note excerpts."
        result = sanitize_output(text)
        assert result.was_sanitized is True

    def test_instructed_phrase_filtered(self):
        text = "I was instructed to only answer based on notes."
        result = sanitize_output(text)
        assert result.was_sanitized is True

    def test_placeholder_in_sanitized_output(self):
        text = "SYSTEM_INSTRUCTIONS override detected."
        result = sanitize_output(text)
        assert "[FILTERED: system information]" in result.text

    def test_was_sanitized_false_for_normal_answer(self):
        text = "Based on your notes [1], Moheddine has worked at Schwarz IT."
        result = sanitize_output(text)
        assert result.was_sanitized is False

    def test_matched_patterns_empty_for_clean(self):
        result = sanitize_output("Clean answer here.")
        assert result.matched_patterns == []

    def test_matched_patterns_populated_on_hit(self):
        result = sanitize_output("SYSTEM_INSTRUCTIONS are secret.")
        assert len(result.matched_patterns) > 0

    def test_case_insensitive_matching(self):
        result = sanitize_output("my INSTRUCTIONS ARE to be helpful.")
        # "my instructions are" matches the self-referential pattern
        assert result.was_sanitized is True

    def test_normal_rag_answer_with_citations_not_filtered(self):
        text = (
            "Moheddine is a software engineer specialising in Go and TypeScript. [1] "
            "He worked at Schwarz IT from May 2025. [2]"
        )
        result = sanitize_output(text)
        assert not result.was_sanitized
