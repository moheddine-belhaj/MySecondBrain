import { defineStore } from "pinia";
import type { NoteSource, UiChatMessage } from "~/types";
import { chatApi } from "~/services/api";

export const useChatStore = defineStore("chat", () => {
  const messages = ref<UiChatMessage[]>([]);
  const sessionId = ref<string | null>(null);
  const isLoading = ref(false);
  const error = ref<string | null>(null);

  function addUserMessage(content: string): UiChatMessage {
    const msg: UiChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content,
      createdAt: new Date().toISOString(),
    };
    messages.value.push(msg);
    return msg;
  }

  function addAssistantPlaceholder(): UiChatMessage {
    const msg: UiChatMessage = {
      id: crypto.randomUUID(),
      role: "assistant",
      content: "",
      isStreaming: true,
      createdAt: new Date().toISOString(),
    };
    messages.value.push(msg);
    return msg;
  }

  function appendDelta(id: string, delta: string) {
    const msg = messages.value.find((m) => m.id === id);
    if (msg) msg.content += delta;
  }

  function finaliseAssistant(id: string, sources: NoteSource[], newSessionId: string | null) {
    const msg = messages.value.find((m) => m.id === id);
    if (msg) {
      msg.isStreaming = false;
      msg.sources = sources;
    }
    if (newSessionId) sessionId.value = newSessionId;
  }

  async function sendBlocking(content: string) {
    error.value = null;
    isLoading.value = true;
    addUserMessage(content);

    try {
      const history = messages.value
        .filter((m) => !m.isStreaming)
        .map(({ role, content }) => ({ role, content }));

      const res = await chatApi.sendMessage(history, sessionId.value ?? undefined);

      const assistant: UiChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: res.answer,
        sources: res.sources,
        createdAt: new Date().toISOString(),
      };
      messages.value.push(assistant);
      sessionId.value = res.session_id;
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : "Request failed";
    } finally {
      isLoading.value = false;
    }
  }

  function clearSession() {
    messages.value = [];
    sessionId.value = null;
    error.value = null;
  }

  return {
    messages,
    sessionId,
    isLoading,
    error,
    addUserMessage,
    addAssistantPlaceholder,
    appendDelta,
    finaliseAssistant,
    sendBlocking,
    clearSession,
  };
});
