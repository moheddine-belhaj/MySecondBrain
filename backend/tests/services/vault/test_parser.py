from datetime import datetime, timezone

import pytest

from app.services.vault.models import Heading
from app.services.vault.parser import MarkdownParser


# ── extract_frontmatter ───────────────────────────────────────────────────────

def test_frontmatter_basic():
    raw = "---\ntitle: My Note\ntags: [python, ai]\n---\n# Hello"
    fm, body = MarkdownParser.extract_frontmatter(raw)
    assert fm["title"] == "My Note"
    assert fm["tags"] == ["python", "ai"]
    assert "# Hello" in body


def test_frontmatter_missing():
    raw = "# Just a heading\nNo frontmatter here."
    fm, body = MarkdownParser.extract_frontmatter(raw)
    assert fm == {}
    assert raw == body


def test_frontmatter_invalid_yaml_returns_empty():
    raw = "---\n: : invalid: yaml: [\n---\n# Body"
    fm, body = MarkdownParser.extract_frontmatter(raw)
    assert fm == {}
    assert "# Body" in body


def test_frontmatter_non_dict_yaml_returns_empty():
    # YAML that parses to a list, not a dict
    raw = "---\n- item1\n- item2\n---\n# Body"
    fm, body = MarkdownParser.extract_frontmatter(raw)
    assert fm == {}


def test_frontmatter_windows_line_endings():
    raw = "---\r\ntitle: Win\r\n---\r\n# Body"
    fm, body = MarkdownParser.extract_frontmatter(raw)
    assert fm["title"] == "Win"


def test_frontmatter_empty_block():
    raw = "---\n---\n# Body"
    fm, body = MarkdownParser.extract_frontmatter(raw)
    assert fm == {}
    assert "# Body" in body


# ── extract_headings ──────────────────────────────────────────────────────────

def test_headings_all_levels():
    text = "# H1\n## H2\n### H3\n#### H4\n##### H5\n###### H6"
    headings = MarkdownParser.extract_headings(text)
    assert headings == [
        Heading(1, "H1"),
        Heading(2, "H2"),
        Heading(3, "H3"),
        Heading(4, "H4"),
        Heading(5, "H5"),
        Heading(6, "H6"),
    ]


def test_headings_strips_trailing_hashes():
    text = "## Section ##"
    headings = MarkdownParser.extract_headings(text)
    assert headings[0].text == "Section"


def test_headings_not_in_inline():
    # A hash mid-line is not a heading
    text = "Some text with a #tag and ## also not heading"
    headings = MarkdownParser.extract_headings(text)
    assert headings == []


def test_headings_empty():
    assert MarkdownParser.extract_headings("No headings here.") == []


# ── extract_wikilinks ─────────────────────────────────────────────────────────

def test_wikilinks_simple():
    text = "See [[My Note]] for details."
    assert MarkdownParser.extract_wikilinks(text) == ["My Note"]


def test_wikilinks_with_alias():
    text = "Read [[Note Title|this note]] now."
    assert MarkdownParser.extract_wikilinks(text) == ["Note Title"]


def test_wikilinks_nested_path():
    text = "[[Folder/Sub Folder/Note]]"
    assert MarkdownParser.extract_wikilinks(text) == ["Folder/Sub Folder/Note"]


def test_wikilinks_with_heading_anchor():
    # [[Note#Heading]] — target is "Note", heading stripped
    text = "[[Note#Section One]]"
    assert MarkdownParser.extract_wikilinks(text) == ["Note"]


def test_wikilinks_multiple():
    text = "See [[A]] and [[B]] and [[C]]."
    assert MarkdownParser.extract_wikilinks(text) == ["A", "B", "C"]


def test_wikilinks_none():
    assert MarkdownParser.extract_wikilinks("No links here.") == []


# ── extract_tags ─────────────────────────────────────────────────────────────

def test_tags_from_frontmatter_list():
    fm = {"tags": ["Python", "AI"]}
    tags = MarkdownParser.extract_tags(fm, "")
    assert "python" in tags
    assert "ai" in tags


def test_tags_from_frontmatter_string():
    fm = {"tags": "single-tag"}
    tags = MarkdownParser.extract_tags(fm, "")
    assert "single-tag" in tags


def test_tags_inline():
    tags = MarkdownParser.extract_tags({}, "This uses #machine-learning and #ai.")
    assert "machine-learning" in tags
    assert "ai" in tags


def test_tags_deduplication():
    fm = {"tags": ["AI"]}
    body = "Also #ai mentioned inline."
    tags = MarkdownParser.extract_tags(fm, body)
    assert tags.count("ai") == 1


def test_tags_url_anchor_not_captured():
    # # in a URL should not be treated as a tag
    body = "Visit https://example.com/#section for details."
    tags = MarkdownParser.extract_tags({}, body)
    assert "section" not in tags


def test_tags_frontmatter_order_preserved():
    fm = {"tags": ["first", "second"]}
    tags = MarkdownParser.extract_tags(fm, "#third")
    assert tags.index("first") < tags.index("second") < tags.index("third")


# ── derive_title ──────────────────────────────────────────────────────────────

def test_title_from_frontmatter():
    fm = {"title": "FM Title"}
    headings = [Heading(1, "H1 Title")]
    assert MarkdownParser.derive_title(fm, headings, "stem") == "FM Title"


def test_title_from_h1_when_no_frontmatter():
    headings = [Heading(2, "H2"), Heading(1, "H1 Title")]
    assert MarkdownParser.derive_title({}, headings, "stem") == "H1 Title"


def test_title_fallback_to_stem():
    assert MarkdownParser.derive_title({}, [], "my-note-file") == "my-note-file"


def test_title_strips_whitespace():
    fm = {"title": "  Padded Title  "}
    assert MarkdownParser.derive_title(fm, [], "stem") == "Padded Title"


# ── parse_datetime ────────────────────────────────────────────────────────────

def test_parse_datetime_iso_full():
    dt = MarkdownParser.parse_datetime("2024-01-15T10:30:00")
    assert dt == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


def test_parse_datetime_iso_no_seconds():
    dt = MarkdownParser.parse_datetime("2024-01-15T10:30")
    assert dt == datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)


def test_parse_datetime_date_only():
    dt = MarkdownParser.parse_datetime("2024-01-15")
    assert dt == datetime(2024, 1, 15, tzinfo=timezone.utc)


def test_parse_datetime_pyyaml_object():
    # PyYAML auto-parses YYYY-MM-DD as a date object — we accept datetime too
    import datetime as dt_module
    naive = dt_module.datetime(2024, 3, 10, 12, 0)
    result = MarkdownParser.parse_datetime(naive)
    assert result.tzinfo == timezone.utc


def test_parse_datetime_invalid_string():
    assert MarkdownParser.parse_datetime("not-a-date") is None


def test_parse_datetime_none():
    assert MarkdownParser.parse_datetime(None) is None


def test_parse_datetime_integer():
    assert MarkdownParser.parse_datetime(12345) is None
