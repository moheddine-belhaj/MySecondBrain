# tests

Pytest suite (`asyncio_mode = auto`). Run from `backend/` with `pytest`.

- `unit/`: app-level tests (e.g. `test_startup.py`)
- `integration/`: reserved for tests against real services
- `services/<name>/`: one folder per service, mirroring `app/services/` (vault, ingestion, indexing, vector, retrieval, synthesis, session, security)

Test files are named `test_<module>.py`.
