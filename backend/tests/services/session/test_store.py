"""Unit tests for SessionStore and ConversationSession."""

import time

import pytest

from app.services.session.store import ConversationMessage, ConversationSession, SessionStore


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _store(**kwargs) -> SessionStore:
    return SessionStore(**kwargs)


# ── Tests: get_or_create ──────────────────────────────────────────────────────


class TestGetOrCreate:
    def test_returns_session(self):
        store = _store()
        session = store.get_or_create()
        assert isinstance(session, ConversationSession)

    def test_auto_generates_uuid_when_no_id_given(self):
        store = _store()
        session = store.get_or_create()
        assert len(session.session_id) == 36  # UUID4 format

    def test_new_session_has_no_messages(self):
        store = _store()
        session = store.get_or_create()
        assert session.messages == []

    def test_same_id_returns_same_session(self):
        store = _store()
        s1 = store.get_or_create("abc")
        s2 = store.get_or_create("abc")
        assert s1 is s2

    def test_different_ids_return_different_sessions(self):
        store = _store()
        s1 = store.get_or_create("id-1")
        s2 = store.get_or_create("id-2")
        assert s1.session_id != s2.session_id

    def test_creates_session_with_provided_id(self):
        store = _store()
        session = store.get_or_create("my-id")
        assert session.session_id == "my-id"

    def test_unknown_id_creates_new_session(self):
        store = _store()
        session = store.get_or_create("never-seen-before")
        assert session.session_id == "never-seen-before"

    def test_evicts_oldest_when_full(self):
        store = _store(max_sessions=2)
        store.get_or_create("a")
        store.get_or_create("b")
        store.get_or_create("c")  # triggers eviction of "a" (oldest)
        assert store.count() == 2
        assert store.get("c") is not None

    def test_expired_sessions_evicted_on_access(self):
        store = _store(ttl_seconds=1.0)
        session = store.get_or_create("old")
        session.last_active = time.time() - 2.0  # manually expire
        store.get_or_create("trigger")  # triggers _evict_expired
        assert store.get("old") is None


# ── Tests: get ────────────────────────────────────────────────────────────────


class TestGet:
    def test_returns_none_for_missing_id(self):
        store = _store()
        assert store.get("no-such-id") is None

    def test_returns_session_for_existing_id(self):
        store = _store()
        store.get_or_create("sid")
        assert store.get("sid") is not None

    def test_returns_none_after_deletion(self):
        store = _store()
        store.get_or_create("sid")
        store.delete("sid")
        assert store.get("sid") is None

    def test_returns_none_for_expired_session(self):
        store = _store(ttl_seconds=1.0)
        session = store.get_or_create("sid")
        session.last_active = time.time() - 2.0
        assert store.get("sid") is None


# ── Tests: add_message ────────────────────────────────────────────────────────


class TestAddMessage:
    def test_message_stored(self):
        store = _store()
        store.get_or_create("sid")
        store.add_message("sid", "user", "Hello")
        session = store.get("sid")
        assert session is not None
        assert len(session.messages) == 1

    def test_message_role_and_content_correct(self):
        store = _store()
        store.get_or_create("sid")
        store.add_message("sid", "user", "What is RAG?")
        msg = store.get("sid").messages[0]  # type: ignore[union-attr]
        assert msg.role == "user"
        assert msg.content == "What is RAG?"

    def test_messages_preserve_order(self):
        store = _store()
        store.get_or_create("sid")
        store.add_message("sid", "user", "First")
        store.add_message("sid", "assistant", "Second")
        msgs = store.get("sid").messages  # type: ignore[union-attr]
        assert msgs[0].content == "First"
        assert msgs[1].content == "Second"

    def test_history_trimmed_to_max(self):
        store = _store(max_history=4)
        store.get_or_create("sid")
        for i in range(10):
            store.add_message("sid", "user", f"msg{i}")
        session = store.get("sid")
        assert session is not None
        assert len(session.messages) == 4
        assert session.messages[-1].content == "msg9"

    def test_trimmed_keeps_most_recent(self):
        store = _store(max_history=2)
        store.get_or_create("sid")
        store.add_message("sid", "user", "old")
        store.add_message("sid", "assistant", "old-reply")
        store.add_message("sid", "user", "new")
        session = store.get("sid")
        assert session is not None
        assert session.messages[0].content == "old-reply"
        assert session.messages[1].content == "new"

    def test_add_to_nonexistent_session_is_noop(self):
        store = _store()
        store.add_message("ghost", "user", "Hello")  # should not raise
        assert store.get("ghost") is None

    def test_message_has_timestamp(self):
        store = _store()
        store.get_or_create("sid")
        before = time.time()
        store.add_message("sid", "user", "hi")
        after = time.time()
        msg = store.get("sid").messages[0]  # type: ignore[union-attr]
        assert before <= msg.timestamp <= after


# ── Tests: delete ─────────────────────────────────────────────────────────────


class TestDelete:
    def test_returns_true_when_session_exists(self):
        store = _store()
        store.get_or_create("sid")
        assert store.delete("sid") is True

    def test_returns_false_when_session_missing(self):
        store = _store()
        assert store.delete("nope") is False

    def test_session_gone_after_delete(self):
        store = _store()
        store.get_or_create("sid")
        store.delete("sid")
        assert store.get("sid") is None

    def test_count_decreases_after_delete(self):
        store = _store()
        store.get_or_create("a")
        store.get_or_create("b")
        store.delete("a")
        assert store.count() == 1


# ── Tests: count ──────────────────────────────────────────────────────────────


class TestCount:
    def test_zero_at_start(self):
        store = _store()
        assert store.count() == 0

    def test_increments_on_create(self):
        store = _store()
        store.get_or_create("a")
        store.get_or_create("b")
        assert store.count() == 2

    def test_does_not_double_count_same_id(self):
        store = _store()
        store.get_or_create("same")
        store.get_or_create("same")
        assert store.count() == 1
