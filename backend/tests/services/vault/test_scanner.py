"""Scanner tests use tmp_path (pytest built-in) to create real temp directories.

No mocking — the scanner does real filesystem I/O, so we test it that way.
asyncio.run() wraps async calls so these tests run without any pytest-asyncio
configuration.
"""

import asyncio
from pathlib import Path

import pytest

from app.services.vault.scanner import VaultScanner


# ── helpers ───────────────────────────────────────────────────────────────────

def _scan(vault: Path):
    return asyncio.run(VaultScanner(vault).scan())


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ── basic discovery ───────────────────────────────────────────────────────────

def test_finds_markdown_files(tmp_path):
    _write(tmp_path / "note.md", "# Note")
    _write(tmp_path / "sub" / "deep.md", "# Deep")
    (tmp_path / "image.png").write_bytes(b"\x89PNG")

    result = _scan(tmp_path)

    assert len(result.notes) == 2
    assert result.total_files_scanned == 3  # .md, .md, .png
    assert result.skipped_files == 1        # .png


def test_empty_vault(tmp_path):
    result = _scan(tmp_path)
    assert result.notes == []
    assert result.total_files_scanned == 0
    assert result.skipped_files == 0


def test_only_unsupported_files(tmp_path):
    (tmp_path / "doc.pdf").write_bytes(b"%PDF")
    (tmp_path / "data.json").write_text("{}", encoding="utf-8")

    result = _scan(tmp_path)
    assert result.notes == []
    assert result.skipped_files == 2


def test_skips_hidden_files(tmp_path):
    _write(tmp_path / ".hidden.md", "# Hidden")
    _write(tmp_path / "visible.md", "# Visible")

    result = _scan(tmp_path)
    assert len(result.notes) == 1
    assert result.notes[0].title == "Visible"


def test_skips_obsidian_metadata_dir(tmp_path):
    _write(tmp_path / ".obsidian" / "config.md", "# Internal")
    _write(tmp_path / "real.md", "# Real note")

    result = _scan(tmp_path)
    assert len(result.notes) == 1


# ── relative paths ────────────────────────────────────────────────────────────

def test_relative_path_posix_format(tmp_path):
    _write(tmp_path / "folder" / "sub" / "note.md", "# Note")

    result = _scan(tmp_path)
    assert result.notes[0].relative_path == "folder/sub/note.md"


def test_relative_path_top_level(tmp_path):
    _write(tmp_path / "top.md", "# Top")

    result = _scan(tmp_path)
    assert result.notes[0].relative_path == "top.md"


# ── content hashing ───────────────────────────────────────────────────────────

def test_content_hash_is_sha256_hex(tmp_path):
    _write(tmp_path / "note.md", "# Hello")

    result = _scan(tmp_path)
    assert len(result.notes[0].content_hash) == 64   # SHA-256 hex = 64 chars
    assert all(c in "0123456789abcdef" for c in result.notes[0].content_hash)


def test_content_hash_stable_across_scans(tmp_path):
    _write(tmp_path / "note.md", "Same content every time.")

    h1 = _scan(tmp_path).notes[0].content_hash
    h2 = _scan(tmp_path).notes[0].content_hash
    assert h1 == h2


def test_content_hash_changes_on_edit(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("# Version 1", encoding="utf-8")
    hash1 = _scan(tmp_path).notes[0].content_hash

    f.write_text("# Version 2", encoding="utf-8")
    hash2 = _scan(tmp_path).notes[0].content_hash

    assert hash1 != hash2


def test_different_files_have_different_hashes(tmp_path):
    _write(tmp_path / "a.md", "# Note A — unique content")
    _write(tmp_path / "b.md", "# Note B — different content")

    result = _scan(tmp_path)
    hashes = {n.content_hash for n in result.notes}
    assert len(hashes) == 2


# ── metadata extraction ───────────────────────────────────────────────────────

def test_extracts_tags_and_wikilinks(tmp_path):
    _write(tmp_path / "note.md", (
        "---\ntags: [ai, python]\n---\n"
        "# Note\n"
        "See [[Other Note]] and [[Folder/Deep|alias]] for details.\n"
        "Also tagged with #rag."
    ))

    note = _scan(tmp_path).notes[0]
    assert "ai" in note.tags
    assert "python" in note.tags
    assert "rag" in note.tags
    assert "Other Note" in note.wikilinks
    assert "Folder/Deep" in note.wikilinks


def test_title_from_frontmatter(tmp_path):
    _write(tmp_path / "filename.md", "---\ntitle: Custom Title\n---\n# H1 Title")
    note = _scan(tmp_path).notes[0]
    assert note.title == "Custom Title"


def test_title_from_h1(tmp_path):
    _write(tmp_path / "filename.md", "# The Real Title\n\nBody text.")
    note = _scan(tmp_path).notes[0]
    assert note.title == "The Real Title"


def test_title_fallback_to_filename_stem(tmp_path):
    _write(tmp_path / "my-note-file.md", "Just some body text, no heading.")
    note = _scan(tmp_path).notes[0]
    assert note.title == "my-note-file"


def test_created_at_from_frontmatter(tmp_path):
    _write(tmp_path / "note.md", "---\ncreated: 2023-06-15\n---\n# Note")
    note = _scan(tmp_path).notes[0]
    assert note.created_at is not None
    assert note.created_at.year == 2023
    assert note.created_at.month == 6


def test_modified_at_is_utc_aware(tmp_path):
    from datetime import timezone
    _write(tmp_path / "note.md", "# Note")
    note = _scan(tmp_path).notes[0]
    assert note.modified_at.tzinfo == timezone.utc


def test_file_size_correct(tmp_path):
    content = "# Note\nSome content here."
    f = tmp_path / "note.md"
    f.write_text(content, encoding="utf-8")

    note = _scan(tmp_path).notes[0]
    assert note.file_size_bytes == f.stat().st_size


# ── robustness ────────────────────────────────────────────────────────────────

def test_invalid_utf8_survives(tmp_path):
    (tmp_path / "bad.md").write_bytes(b"# Title\n\xff\xfe corrupted bytes")

    result = _scan(tmp_path)
    assert len(result.notes) == 1   # didn't crash, note still returned
    assert "Title" in result.notes[0].raw_content


def test_invalid_frontmatter_yaml_survives(tmp_path):
    _write(tmp_path / "note.md", "---\n: : broken\n---\n# Body")

    result = _scan(tmp_path)
    assert len(result.notes) == 1
    assert result.notes[0].frontmatter == {}


def test_scan_duration_populated(tmp_path):
    _write(tmp_path / "note.md", "# Note")
    result = _scan(tmp_path)
    assert result.scan_duration_ms >= 0


# ── nested folder structure ───────────────────────────────────────────────────

def test_deeply_nested_folders(tmp_path):
    _write(tmp_path / "a" / "b" / "c" / "d" / "deep.md", "# Deep")

    result = _scan(tmp_path)
    assert len(result.notes) == 1
    assert result.notes[0].relative_path == "a/b/c/d/deep.md"


def test_mixed_depth_notes(tmp_path):
    _write(tmp_path / "root.md", "# Root")
    _write(tmp_path / "level1" / "note.md", "# Level 1")
    _write(tmp_path / "level1" / "level2" / "note.md", "# Level 2")

    result = _scan(tmp_path)
    paths = {n.relative_path for n in result.notes}
    assert paths == {"root.md", "level1/note.md", "level1/level2/note.md"}
