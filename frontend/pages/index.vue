<script setup lang="ts">
import { useChatStore } from "~/stores/chat";
import { storeToRefs } from "pinia";
import { useStream } from "~/composables/useStream";

definePageMeta({ layout: "default" });

const config = useRuntimeConfig();
const chat = useChatStore();
const { messages, isLoading, error, sessionId } = storeToRefs(chat);
const { start: startStream, isStreaming } = useStream();

const input = ref("");
const inputEl = ref<HTMLTextAreaElement | null>(null);

async function send() {
  const text = input.value.trim();
  if (!text || isLoading.value || isStreaming.value) return;
  input.value = "";

  chat.addUserMessage(text);
  const placeholder = chat.addAssistantPlaceholder();

  await startStream({
    url: `${config.public.apiBase}/chat/rag/stream`,
    body: {
      messages: messages.value
        .filter((m) => m.id !== placeholder.id && !m.isStreaming)
        .map(({ role, content }) => ({ role, content })),
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
        chat.finaliseAssistant(placeholder.id, [], null);
      }
    },
  });
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
}

const messagesEl = ref<HTMLElement | null>(null);
watch(messages, async () => {
  await nextTick();
  if (messagesEl.value) {
    messagesEl.value.scrollTop = messagesEl.value.scrollHeight;
  }
}, { deep: true });
</script>

<template>
  <div class="flex flex-col h-full">

    <!-- Message list -->
    <div ref="messagesEl" class="flex-1 overflow-y-auto px-6 py-4 space-y-4">
      <!-- Empty state -->
      <div v-if="!messages.length" class="flex flex-col items-center justify-center h-full gap-4 text-center">
        <span class="text-4xl">🧠</span>
        <p class="text-gray-500 dark:text-gray-400 text-sm max-w-xs">
          Ask anything about your Obsidian vault. The AI will search your notes and answer from them.
        </p>
      </div>

      <!-- Messages -->
      <div
        v-for="msg in messages"
        :key="msg.id"
        :class="[
          'flex gap-3 max-w-3xl',
          msg.role === 'user' ? 'ml-auto flex-row-reverse' : '',
        ]"
      >
        <!-- Avatar -->
        <div
          :class="[
            'w-7 h-7 rounded-full flex items-center justify-center text-xs shrink-0 mt-0.5',
            msg.role === 'user'
              ? 'bg-brand-600 text-white'
              : 'bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300',
          ]"
        >
          {{ msg.role === 'user' ? 'U' : '🧠' }}
        </div>

        <!-- Bubble -->
        <div
          :class="[
            'px-4 py-3 rounded-2xl text-sm leading-relaxed max-w-[75%]',
            msg.role === 'user'
              ? 'bg-brand-600 text-white rounded-tr-sm'
              : 'bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 text-gray-800 dark:text-gray-200 rounded-tl-sm',
          ]"
        >
          <span v-if="msg.isStreaming && !msg.content" class="inline-flex gap-1">
            <span class="w-1.5 h-1.5 rounded-full bg-current animate-bounce [animation-delay:0ms]" />
            <span class="w-1.5 h-1.5 rounded-full bg-current animate-bounce [animation-delay:150ms]" />
            <span class="w-1.5 h-1.5 rounded-full bg-current animate-bounce [animation-delay:300ms]" />
          </span>
          <span v-else class="whitespace-pre-wrap">{{ msg.content }}</span>

          <!-- Sources -->
          <div v-if="msg.sources?.length" class="mt-2 pt-2 border-t border-gray-200 dark:border-gray-700 space-y-1">
            <p class="text-xs text-gray-400 dark:text-gray-500 font-medium">Sources</p>
            <div
              v-for="src in msg.sources"
              :key="src.note_path"
              class="text-xs text-gray-500 dark:text-gray-400 truncate"
            >
              📄 {{ src.note_title }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Error -->
    <p v-if="error" class="px-6 py-1 text-xs text-red-500 dark:text-red-400">{{ error }}</p>

    <!-- Input -->
    <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
      <div class="flex gap-2 items-end max-w-3xl mx-auto">
        <textarea
          ref="inputEl"
          v-model="input"
          rows="1"
          class="input flex-1 resize-none max-h-40 overflow-y-auto"
          placeholder="Ask your vault..."
          :disabled="isLoading || isStreaming"
          @keydown="onKeydown"
        />
        <button
          class="btn-primary h-10 shrink-0"
          :disabled="!input.trim() || isLoading || isStreaming"
          @click="send"
        >
          Send
        </button>
        <button
          v-if="messages.length"
          class="btn-ghost h-10 shrink-0"
          title="Clear conversation"
          @click="chat.clearSession"
        >
          <AppIcon name="x" class="w-4 h-4" />
        </button>
      </div>
    </div>

  </div>
</template>
