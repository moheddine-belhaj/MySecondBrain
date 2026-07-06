<script setup lang="ts">
import { useChatStore } from "~/stores/chat";
import { storeToRefs } from "pinia";
import { useStream } from "~/composables/useStream";

definePageMeta({ layout: "default" });

const config = useRuntimeConfig();
const chat = useChatStore();
const { messages, sessionId } = storeToRefs(chat);
const { start: startStream, stop: stopStream, isStreaming } = useStream();

const streamError = ref<string | null>(null);
const isBusy = computed(() => isStreaming.value);

async function handleSend(text: string) {
  if (isBusy.value) return;
  streamError.value = null;

  chat.addUserMessage(text);
  const placeholder = chat.addAssistantPlaceholder();

  // Build history excluding the streaming placeholder
  const history = messages.value
    .filter((m) => !m.isStreaming)
    .map(({ role, content }) => ({ role, content }));

  await startStream({
    url: `${config.public.apiBase}/chat/rag/stream`,
    body: {
      messages: history,
      session_id: sessionId.value ?? null,
    },
    onEvent(event) {
      if (event.type === "delta") {
        chat.appendDelta(placeholder.id, event.delta);
      }
      if (event.type === "done") {
        chat.finaliseAssistant(placeholder.id, event.sources, event.session_id);
      }
      if (event.type === "error") {
        const msg = event.error || "The assistant encountered an error.";
        chat.setError(placeholder.id, msg);
        streamError.value = msg;
      }
    },
    onError(err) {
      const msg = err.includes("400")
        ? "Request rejected — your message may contain disallowed content."
        : err.includes("429")
          ? "Too many requests — please wait a moment."
          : `Connection error: ${err}`;
      chat.setError(placeholder.id, msg);
      streamError.value = msg;
    },
  });
}

function handleClear() {
  stopStream();
  chat.clearSession();
  streamError.value = null;
}
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Messages area -->
    <ChatMessages :messages="messages" />

    <!-- Inline stream error banner (fades out after user sends next message) -->
    <Transition name="slide-up">
      <div
        v-if="streamError"
        class="px-4 py-2 bg-red-50 dark:bg-red-950/40 border-t border-red-200 dark:border-red-800"
      >
        <div class="max-w-3xl mx-auto flex items-center justify-between gap-3">
          <div class="flex items-center gap-2 text-xs text-red-600 dark:text-red-400">
            <AppIcon name="alert" class="w-3.5 h-3.5 shrink-0" />
            {{ streamError }}
          </div>
          <button
            class="text-xs text-red-400 dark:text-red-600 hover:text-red-600 dark:hover:text-red-400 transition-colors shrink-0"
            @click="streamError = null"
          >
            Dismiss
          </button>
        </div>
      </div>
    </Transition>

    <!-- Toolbar: stop streaming / clear session -->
    <div
      v-if="messages.length"
      class="flex items-center justify-center gap-3 py-1.5 bg-white/80 dark:bg-gray-950/80"
    >
      <button
        v-if="isStreaming"
        class="btn-ghost text-xs px-3 py-1 h-auto border border-gray-200 dark:border-gray-700"
        @click="stopStream"
      >
        <AppIcon name="x" class="w-3 h-3" />
        Stop
      </button>
      <button
        v-else
        class="btn-ghost text-xs px-3 py-1 h-auto text-gray-400 dark:text-gray-600 hover:text-gray-600"
        @click="handleClear"
      >
        <AppIcon name="trash" class="w-3 h-3" />
        Clear chat
      </button>
    </div>

    <!-- Input -->
    <ChatInput :disabled="isBusy" @send="handleSend" />
  </div>
</template>

<style scoped>
.slide-up-enter-active,
.slide-up-leave-active {
  transition: all 0.2s ease;
}
.slide-up-enter-from,
.slide-up-leave-to {
  opacity: 0;
  transform: translateY(4px);
}
</style>
