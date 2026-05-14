# MySecondBrain
My personal LLM

# Initial overview of the project architecture:


                ┌───────────────────┐
                │   Obsidian Vault  │
                └─────────┬─────────┘
                          │
                    File Watcher
                          │
                ┌─────────▼─────────┐
                │  Ingestion Engine │
                └─────────┬─────────┘
                          │
                Markdown Processing
                          │
                     Chunking
                          │
                ┌─────────▼─────────┐
                │ Embedding Service │
                └─────────┬─────────┘
                          │
                ┌─────────▼─────────┐
                │   Vector Database │
                └─────────┬─────────┘
                          │
                 Retrieval Pipeline
                          │
          ┌───────────────┴──────────────┐
          │                              │
     Prompt Guard                 Metadata Filters
          │                              │
          └───────────────┬──────────────┘
                          │
                ┌─────────▼─────────┐
                │   LLM Gateway     │
                └─────────┬─────────┘
                          │
                ┌─────────▼─────────┐
                │ FastAPI Backend   │
                └─────────┬─────────┘
                          │
                ┌─────────▼─────────┐
                │   Next.js Client  │
                └───────────────────┘
