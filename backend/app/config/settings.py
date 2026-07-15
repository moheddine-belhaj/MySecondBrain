from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Application ───────────────────────────────────────────────────────────
    app_name: str = "Second Brain API"
    app_version: str = "0.1.0"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"

    # ── Logging ───────────────────────────────────────────────────────────────
    # log_format: "json" for production (machine-readable), "console" for local dev
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    # ── CORS ──────────────────────────────────────────────────────────────────
    allowed_origins: list[str] = ["http://localhost:3000"]

    # ── Qdrant ────────────────────────────────────────────────────────────────
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "second_brain"

    # ── Ollama ────────────────────────────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"
    ollama_embed_model: str = "nomic-embed-text"
    ollama_chat_model: str = "qwen2.5"

    # Timeouts (seconds)
    # connect_timeout: how long to wait for the TCP handshake
    # chat_timeout: generation can be slow on CPU — 120 s is conservative
    # embed_timeout: embedding is fast — 30 s is generous
    ollama_connect_timeout: float = 5.0
    ollama_chat_timeout: float = 120.0
    ollama_embed_timeout: float = 30.0

    # Retry config
    ollama_max_retries: int = 3
    ollama_retry_delay: float = 0.5

    # ── Synthesis (LlamaIndex) ────────────────────────────────────────────────
    # Response mode passed to LlamaIndex get_response_synthesizer().
    # compact       — pack all chunks into one prompt; fast, works for most queries.
    # refine        — iterates chunk-by-chunk, refining the answer; slower but
    #                 better when chunks are long or context window is small.
    # tree_summarize — builds a tree of summaries; best for very long contexts.
    synthesis_mode: Literal["compact", "refine", "tree_summarize"] = "compact"

    # ── Retrieval ─────────────────────────────────────────────────────────────
    retrieval_top_k: int = 10
    retrieval_score_threshold: float = 0.0
    # Max chunks from a single note_id in one result set (diversity control).
    retrieval_max_chunks_per_note: int = 2
    # Qdrant fetch limit = top_k × this factor (headroom for dedup losses).
    retrieval_over_fetch_factor: int = 3

    # ── Hybrid search ─────────────────────────────────────────────────────────
    # Default mode: "semantic" (vector only), "keyword" (BM25 only), "hybrid" (both).
    hybrid_default_mode: str = "hybrid"
    # RRF weights — control how much each signal influences the fused ranking.
    # semantic_weight=1.0, keyword_weight=0.0 is equivalent to pure semantic.
    hybrid_semantic_weight: float = 0.7
    hybrid_keyword_weight: float = 0.3
    # RRF k-parameter (60 is the Cormack et al. standard; lower = more top-rank bias).
    hybrid_rrf_k: int = 60

    # ── Vault ─────────────────────────────────────────────────────────────────
    vault_path: str = "./vault"

    # ── Incremental indexing ───────────────────────────────────────────────────
    # Path where the sync engine writes its {note_path: hash} state file.
    index_state_path: str = "./data/index_state.json"
    # 0 = scheduler disabled; >0 = run sync every N minutes automatically.
    sync_interval_minutes: int = 0

    # ── Ingestion ─────────────────────────────────────────────────────────────
    chunk_size: int = 512
    chunk_overlap: int = 64
    # Number of chunks per Ollama /api/embed call. Larger = fewer round-trips;
    # smaller = less data lost on a single batch failure.
    embed_batch_size: int = 32
    # Must match the embedding model's output dimension.
    # nomic-embed-text → 768, mxbai-embed-large → 1024
    qdrant_vector_size: int = 768

    @property
    def qdrant_url(self) -> str:
        return f"http://{self.qdrant_host}:{self.qdrant_port}"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


settings = Settings()
