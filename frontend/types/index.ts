// ── Chat ─────────────────────────────────────────────────────────────────────

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface NoteSource {
  note_title: string;
  note_path: string;
  excerpt: string;
  score: number;
}

export interface RagChatRequest {
  messages: ChatMessage[];
  session_id?: string | null;
  top_k?: number;
  score_threshold?: number;
  tags?: string[] | null;
  note_path?: string | null;
  deduplicate?: boolean;
}

export interface ChatResponse {
  answer: string;
  session_id: string;
  sources: NoteSource[];
  candidate_count: number;
}

export type StreamEventType = "retrieval" | "delta" | "done" | "error";

export interface StreamEvent {
  type: StreamEventType;
  delta: string;
  done: boolean;
  session_id: string | null;
  sources: NoteSource[];
  candidate_count: number;
  error: string;
}

// UI-enriched message (adds id + timestamp for rendering)
export interface UiChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: NoteSource[];
  isStreaming?: boolean;
  createdAt: string;
}

// ── Session ───────────────────────────────────────────────────────────────────

export interface ConversationHistory {
  session_id: string;
  messages: ChatMessage[];
  created_at: string;
  last_active: string;
  message_count: number;
}

export interface SessionInfo {
  session_id: string;
  deleted: boolean;
}

// ── Search ────────────────────────────────────────────────────────────────────

export interface SearchRequest {
  q: string;
  top_k?: number;
  score_threshold?: number;
  tags?: string[];
  note_path?: string;
}

export interface RetrievedChunk {
  score: number;
  rank: number;
  chunk_text: string;
  note_title: string;
  note_path: string;
  tags: string[];
  heading_path: string[];
  chunk_index: number;
  total_chunks: number;
  word_count: number;
  note_modified_at: string;
}

export interface SearchResponse {
  query: string;
  chunks: RetrievedChunk[];
  total: number;
  top_k: number;
}

// ── Ingest ────────────────────────────────────────────────────────────────────

export interface IngestStatus {
  status: "pending" | "running" | "completed" | "failed";
  total_notes: number;
  processed_notes: number;
  message?: string;
}

export interface ScanResponse {
  vault_path: string;
  total_notes: number;
  notes: string[];
}

// ── Health ────────────────────────────────────────────────────────────────────

export interface HealthResponse {
  status: "ok" | "degraded" | "error";
  components: Record<string, "ok" | "degraded" | "error" | string>;
  version?: string;
}

// ── UI State ──────────────────────────────────────────────────────────────────

export type Theme = "light" | "dark" | "system";

export interface ApiError {
  detail: string;
  status: number;
}
