# requirements

| File | Use |
|------|-----|
| `base.txt` | Full runtime dependencies, including the AI stack (LlamaIndex, Qdrant client, ...). The Docker image installs this |
| `server.txt` | Minimal install to run the bare FastAPI server, without the AI/ML stack |
| `dev.txt` | `base.txt` plus test and lint tools (pytest, pytest-asyncio, ruff, ...) |

Local setup: `pip install -r requirements/dev.txt`
