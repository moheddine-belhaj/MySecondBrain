"""Stateless markdown parser for Obsidian-flavoured notes.

All methods are static — no instance state, no I/O.  This makes them
trivially unit-testable: pass in a string, inspect the output.
"""

import re
from datetime import datetime, timezone
from typing import Any

import yaml

from app.services.vault.models import Heading

# ── Compiled regexes ─────────────────────────────────────────────────────────

# YAML frontmatter fence: must start at line 0
_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)

# ATX headings: # … ###### with optional trailing hashes
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)(?:\s+#+)?\s*$", re.MULTILINE)

# Obsidian wikilinks: [[Target]] or [[Target|alias]] or [[Folder/Note]]
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")

# Inline tags: #tag, #nested/tag
# (?<!\S) = "not preceded by non-whitespace", which means the # must be at the
# start of a line or follow whitespace. This stops URL anchors like
# https://example.com/#section from matching (/ is non-whitespace).
_INLINE_TAG_RE = re.compile(r"(?<!\S)#([A-Za-z][A-Za-z0-9_/-]*)")


class MarkdownParser:
    @staticmethod
    def extract_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
        """Split raw markdown into (frontmatter_dict, body).

        Returns ({}, raw) when no frontmatter fence is present or YAML is invalid.
        """
        m = _FRONTMATTER_RE.match(raw)
        if not m:
            return {}, raw
        try:
            data = yaml.safe_load(m.group(1)) or {}
            if not isinstance(data, dict):
                data = {}
        except yaml.YAMLError:
            data = {}
        return data, raw[m.end():]

    @staticmethod
    def extract_headings(text: str) -> list[Heading]:
        return [
            Heading(level=len(m.group(1)), text=m.group(2).strip())
            for m in _HEADING_RE.finditer(text)
        ]

    @staticmethod
    def extract_wikilinks(text: str) -> list[str]:
        """Return link targets in document order, duplicates preserved.

        [[Note|alias]]   → "Note"
        [[Folder/Note]]  → "Folder/Note"
        [[Note#heading]] → "Note"
        """
        return [m.group(1).strip() for m in _WIKILINK_RE.finditer(text)]

    @staticmethod
    def extract_tags(frontmatter: dict[str, Any], body: str) -> list[str]:
        """Merge frontmatter tags and inline #tags into a deduplicated list.

        Order: frontmatter tags first, then inline tags in document order.
        All tags are lowercased and stripped of the leading #.
        """
        seen: set[str] = set()
        tags: list[str] = []

        fm_tags = frontmatter.get("tags", [])
        if isinstance(fm_tags, str):
            fm_tags = [fm_tags]
        for t in fm_tags or []:
            normalized = str(t).lower().strip().lstrip("#")
            if normalized and normalized not in seen:
                seen.add(normalized)
                tags.append(normalized)

        for m in _INLINE_TAG_RE.finditer(body):
            normalized = m.group(1).lower()
            if normalized not in seen:
                seen.add(normalized)
                tags.append(normalized)

        return tags

    @staticmethod
    def derive_title(
        frontmatter: dict[str, Any], headings: list[Heading], stem: str
    ) -> str:
        """Resolve note title with priority: frontmatter > first H1 > filename stem."""
        if title := frontmatter.get("title"):
            return str(title).strip()
        h1 = next((h for h in headings if h.level == 1), None)
        if h1:
            return h1.text
        return stem

    @staticmethod
    def parse_datetime(value: Any) -> datetime | None:
        """Parse frontmatter date values into a UTC-aware datetime.

        Accepts: datetime objects, date objects (PyYAML parses bare YYYY-MM-DD
        as datetime.date, not datetime.datetime), ISO strings, date-only strings.
        Returns None for anything unparseable.
        """
        import datetime as _dt

        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        # PyYAML auto-parses `created: 2023-06-15` as a datetime.date object
        if isinstance(value, _dt.date) and not isinstance(value, datetime):
            return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
        if isinstance(value, str):
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
                try:
                    return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
        return None
