import type { ChatMessage, IngestStatus } from "~/types";

// Thin wrapper around $fetch — real implementations come in later tasks.
export const useApiService = () => {
  const config = useRuntimeConfig();
  const base = config.public.apiBase;

  const chat = (messages: Pick<ChatMessage, "role" | "content">[]) =>
    $fetch<ChatMessage>(`${base}/chat`, { method: "POST", body: { messages } });

  const triggerIngest = () =>
    $fetch<IngestStatus>(`${base}/ingest`, { method: "POST" });

  const getIngestStatus = () =>
    $fetch<IngestStatus>(`${base}/ingest/status`);

  return { chat, triggerIngest, getIngestStatus };
};
