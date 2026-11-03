# services/llm

Provider abstraction for language models.

- `base.py`: contracts `LLMProvider` (`chat`, `chat_stream`, `health`) and `EmbeddingProvider` (`embed`, `embed_batch`, `health`).
- `ollama.py`: `OllamaService`, an httpx wrapper around the Ollama API that implements both. It applies the configured timeouts and retries.
- `schemas.py`: internal request/response types (`LLMMessage` with a `system` role, `LLMOptions`, `StreamDelta`, embedding request/response). These are not API models.

To add another provider, implement the two contracts and swap it in `dependencies.py`.
