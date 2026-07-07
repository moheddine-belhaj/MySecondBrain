import type {
  ChatMessage,
  ChatResponse,
  ConversationHistory,
  HealthResponse,
  IngestStatus,
  RagChatRequest,
  ScanResponse,
  SearchResponse,
  SessionInfo,
} from "~/types";

function useBase() {
  const config = useRuntimeConfig();
  return config.public.apiBase as string;
}

// ── Chat ─────────────────────────────────────────────────────────────────────

export const chatApi = {
  sendMessage(messages: ChatMessage[], sessionId?: string) {
    return $fetch<ChatResponse>(`${useBase()}/chat/rag`, {
      method: "POST",
      body: { messages, session_id: sessionId ?? null } satisfies RagChatRequest,
    });
  },

  streamUrl(base: string) {
    return `${base}/chat/rag/stream`;
  },

  getSession(sessionId: string) {
    return $fetch<ConversationHistory>(`${useBase()}/chat/sessions/${sessionId}`);
  },

  deleteSession(sessionId: string) {
    return $fetch<SessionInfo>(`${useBase()}/chat/sessions/${sessionId}`, {
      method: "DELETE",
    });
  },
};

// ── Search ────────────────────────────────────────────────────────────────────

export const searchApi = {
  search(
    q: string,
    opts?: { topK?: number; scoreThreshold?: number; tags?: string[] }
  ) {
    const params: Record<string, string | number | string[]> = { q };
    if (opts?.topK) params.top_k = opts.topK;
    if (opts?.scoreThreshold) params.score_threshold = opts.scoreThreshold;
    if (opts?.tags?.length) params.tags = opts.tags;
    return $fetch<SearchResponse>(`${useBase()}/search`, { query: params });
  },
};

// ── Ingest ────────────────────────────────────────────────────────────────────

export const ingestApi = {
  triggerIngest() {
    return $fetch<IngestStatus>(`${useBase()}/ingest`, { method: "POST" });
  },

  scan() {
    return $fetch<ScanResponse>(`${useBase()}/ingest/scan`, { method: "POST" });
  },
};

// ── Health ────────────────────────────────────────────────────────────────────

export const healthApi = {
  check() {
    return $fetch<HealthResponse>(`${useBase()}/health`);
  },
};
