import type { StreamEvent } from "~/types";

interface StreamOptions {
  url: string;
  body: Record<string, unknown>;
  onEvent: (event: StreamEvent) => void;
  onError?: (err: string) => void;
  onDone?: () => void;
}

export function useStream() {
  const isStreaming = ref(false);
  let abortController: AbortController | null = null;

  async function start({ url, body, onEvent, onError, onDone }: StreamOptions) {
    if (isStreaming.value) stop();

    isStreaming.value = true;
    abortController = new AbortController();

    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: abortController.signal,
      });

      if (!response.ok || !response.body) {
        onError?.(`HTTP ${response.status}`);
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const payload = line.slice(6).trim();
          if (!payload || payload === "[DONE]") continue;

          try {
            const event = JSON.parse(payload) as StreamEvent;
            onEvent(event);
            if (event.type === "done" || event.type === "error") {
              onDone?.();
              return;
            }
          } catch {
            // malformed SSE line — skip
          }
        }
      }
    } catch (e) {
      if ((e as { name?: string }).name !== "AbortError") {
        onError?.(e instanceof Error ? e.message : "Stream failed");
      }
    } finally {
      isStreaming.value = false;
    }
  }

  function stop() {
    abortController?.abort();
    isStreaming.value = false;
  }

  return { isStreaming: readonly(isStreaming), start, stop };
}
