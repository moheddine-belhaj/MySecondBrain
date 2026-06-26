"""In-memory conversation session store.

Design rationale
----------------
Sessions live in a plain dict on app.state — no Redis, no DB. This is correct
for a local-first, single-process application.  Redis adds operational
complexity with zero benefit when there is only one user.

Eviction strategy
-----------------
Lazy TTL: expired sessions are swept out on every get_or_create() call.
This avoids background tasks, keeps the implementation simple, and is
correct for low-traffic usage (there is always a request to trigger cleanup).

If the session count hits max_sessions, the least-recently-active session
is evicted to make room (LRU).

Conversation history trimming
------------------------------
Sessions keep at most `max_history` messages (user+assistant alternating).
Oldest messages are dropped to stay within the limit.  This means the LLM
sees a sliding window of the conversation, not the full history.  This
prevents context overflow for very long conversations.

asyncio safety
--------------
asyncio is single-threaded — dict operations are atomic.  No locking needed.
Would need an asyncio.Lock if background tasks ever wrote to _sessions.
"""

import time
from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4


@dataclass
class ConversationMessage:
    role: Literal["user", "assistant"]
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConversationSession:
    session_id: str
    messages: list[ConversationMessage] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)


class SessionStore:
    """Thread-safe (asyncio) in-memory store for conversation sessions."""

    def __init__(
        self,
        max_sessions: int = 100,
        max_history: int = 20,
        ttl_seconds: float = 3600.0,
    ) -> None:
        self._sessions: dict[str, ConversationSession] = {}
        self._max_sessions = max_sessions
        self._max_history = max_history
        self._ttl = ttl_seconds

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_or_create(self, session_id: str | None = None) -> ConversationSession:
        """Return an existing session by ID, or create a fresh one.

        If `session_id` is None, a new UUID is generated.
        If the ID was provided but the session expired, a new session is
        created with that same ID so the client's reference stays valid.
        """
        self._evict_expired()

        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            session.last_active = time.time()
            return session

        new_id = session_id or str(uuid4())

        if len(self._sessions) >= self._max_sessions:
            self._evict_oldest()

        session = ConversationSession(session_id=new_id)
        self._sessions[new_id] = session
        return session

    def get(self, session_id: str) -> ConversationSession | None:
        """Return a session by ID, or None if it does not exist or has expired."""
        self._evict_expired()
        return self._sessions.get(session_id)

    def add_message(self, session_id: str, role: Literal["user", "assistant"], content: str) -> None:
        """Append a message to a session and update last_active.

        Silently no-ops if the session does not exist (race: expired mid-request).
        Trims oldest messages when max_history is exceeded.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return
        session.messages.append(ConversationMessage(role=role, content=content))
        if len(session.messages) > self._max_history:
            session.messages = session.messages[-self._max_history :]
        session.last_active = time.time()

    def delete(self, session_id: str) -> bool:
        """Delete a session. Returns True if it existed, False if not."""
        return self._sessions.pop(session_id, None) is not None

    def count(self) -> int:
        """Return number of active (possibly expired) sessions."""
        return len(self._sessions)

    # ── Private helpers ────────────────────────────────────────────────────────

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [
            sid
            for sid, s in self._sessions.items()
            if now - s.last_active > self._ttl
        ]
        for sid in expired:
            del self._sessions[sid]

    def _evict_oldest(self) -> None:
        if not self._sessions:
            return
        oldest_id = min(self._sessions, key=lambda sid: self._sessions[sid].last_active)
        del self._sessions[oldest_id]
