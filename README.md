# MySecondBrain
My personal LLM

# Initial overview of the project architecture:

                ┌──────────────────┐
                │Vue/Nuxt Frontend │
                │ Chat Interface   │
                └────────┬─────────┘
                         │ HTTP/WebSocket
                         ▼
                ┌──────────────────┐
                │ FastAPI Backend  │
                │ API Gateway      │
                └────────┬─────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
┌─────────────┐  ┌──────────────┐  ┌──────────────┐
│ RAG Service │  │ Auth/Security│  │ Chat Memory  │
└──────┬──────┘  └──────────────┘  └──────────────┘
       │
       ▼
┌────────────────────┐
│ LlamaIndex Pipeline│
└─────────┬──────────┘
          │
   ┌──────┼───────────┐
   ▼                  ▼
┌───────────┐   ┌───────────┐
│ Qdrant DB │   │ Ollama    │
│ embeddings│   │ local LLM │
└───────────┘   └───────────┘
          ▲
          │
┌────────────────────┐
│ Obsidian Vault     │
│ Markdown Notes     │
└────────────────────┘