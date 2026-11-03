# services/session

`SessionStore` keeps conversation history **in memory** (lost on restart).

- Defaults: 100 sessions, 20 messages per session, 1 hour TTL.
- When full, the least recently active session is evicted.
- Methods: `get_or_create`, `get`, `add_message`, `delete`, `count`.

Used by the chat endpoints to give the model prior turns when a `session_id` is sent.
