"""Unit tests for IndexStateStore.

All tests use a real temp directory (tmp_path fixture) — no mocking needed
because the store itself is the unit under test and its only dependency is the
filesystem.
"""

import json
from pathlib import Path

import pytest

from app.services.indexing.state_store import IndexStateStore


@pytest.fixture
def store(tmp_path: Path) -> IndexStateStore:
    return IndexStateStore(tmp_path / "data" / "index_state.json")


@pytest.mark.asyncio
async def test_load_returns_empty_when_no_file(store: IndexStateStore) -> None:
    result = await store.load()
    assert result == {}


@pytest.mark.asyncio
async def test_save_and_load_roundtrip(store: IndexStateStore) -> None:
    state = {"notes/a.md": "hash-aaa", "notes/b.md": "hash-bbb"}
    await store.save(state)
    loaded = await store.load()
    assert loaded == state


@pytest.mark.asyncio
async def test_save_creates_parent_directories(tmp_path: Path) -> None:
    nested = IndexStateStore(tmp_path / "deep" / "nested" / "dir" / "state.json")
    await nested.save({"x.md": "h1"})
    assert nested.path.exists()


@pytest.mark.asyncio
async def test_no_tmp_file_left_after_save(store: IndexStateStore) -> None:
    await store.save({"a.md": "h1"})
    tmp = store.path.with_suffix(".tmp")
    assert not tmp.exists()


@pytest.mark.asyncio
async def test_load_corrupted_json_returns_empty(store: IndexStateStore) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{ this is: not valid json }", encoding="utf-8")
    result = await store.load()
    assert result == {}


@pytest.mark.asyncio
async def test_save_overwrites_previous_state(store: IndexStateStore) -> None:
    await store.save({"a.md": "old-hash"})
    await store.save({"a.md": "new-hash", "b.md": "hash-b"})
    loaded = await store.load()
    assert loaded == {"a.md": "new-hash", "b.md": "hash-b"}


@pytest.mark.asyncio
async def test_state_file_is_valid_json(store: IndexStateStore) -> None:
    state = {"notes/a.md": "abc", "notes/b.md": "def"}
    await store.save(state)
    raw = store.path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert parsed == state


@pytest.mark.asyncio
async def test_path_property(store: IndexStateStore, tmp_path: Path) -> None:
    assert store.path == tmp_path / "data" / "index_state.json"
