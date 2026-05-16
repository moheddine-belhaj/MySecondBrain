export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: NoteSource[];
  createdAt: string;
}

export interface NoteSource {
  noteTitle: string;
  notePath: string;
  excerpt: string;
  score: number;
}

export interface IngestStatus {
  status: "pending" | "running" | "completed" | "failed";
  totalNotes: number;
  processedNotes: number;
  message?: string;
}
