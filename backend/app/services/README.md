# services

Business logic, one subfolder per concern. Each depends on abstractions where it matters (e.g. `LLMProvider`, `VectorRepository`) so backends can be swapped or mocked.

| Folder | Responsibility |
|--------|----------------|
| [vault/](vault/README.md) | Read and parse Obsidian notes |
| [ingestion/](ingestion/README.md) | Chunk notes, embed, index |
| [indexing/](indexing/README.md) | Incremental sync of changed notes |
| [llm/](llm/README.md) | Ollama chat and embeddings |
| [vector/](vector/README.md) | Qdrant storage and filtering |
| [retrieval/](retrieval/README.md) | Hybrid search (vector + BM25) |
| [synthesis/](synthesis/README.md) | Build context and generate grounded answers |
| [session/](session/README.md) | In-memory chat history |
| [security/](security/README.md) | Sanitization, injection detection, rate limiting |

## Data flow
```
Indexing:  vault → ingestion (chunk, embed) → vector (Qdrant)
Querying:  question → security → retrieval → synthesis (llm) → security → answer
```
