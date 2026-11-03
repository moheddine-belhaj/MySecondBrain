# services/ingestion

Turns notes into indexed vectors.

- `chunker.py`: `MarkdownChunker`, markdown-aware, three stages:
  1. split at headings (chunks never cross sections, each keeps its heading path)
  2. recursive split by paragraph, line, sentence, then word to fit `CHUNK_SIZE`
  3. add `CHUNK_OVERLAP` words of overlap inside a section

  Each chunk text is prefixed with a breadcrumb like `[Note: Title | Section: A > B]` before embedding.
- `embedder.py`: `EmbeddingPipeline.run()` does scan, chunk, embed in batches (`EMBED_BATCH_SIZE`) and upsert into Qdrant, returning `IndexingStats`.
- `models.py`: `TextChunk`, `ChunkMetadata`, `ChunkResult`.
