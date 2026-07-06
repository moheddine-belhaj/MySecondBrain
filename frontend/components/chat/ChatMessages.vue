<script setup lang="ts">
import type { UiChatMessage } from "~/types";

const props = defineProps<{ messages: UiChatMessage[] }>();

const containerEl = ref<HTMLElement | null>(null);
const shouldAutoScroll = ref(true);

function onScroll() {
  const el = containerEl.value;
  if (!el) return;
  const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
  // Resume auto-scroll only when user is within 80px of the bottom
  shouldAutoScroll.value = distFromBottom < 80;
}

async function scrollToBottom() {
  if (!shouldAutoScroll.value) return;
  await nextTick();
  const el = containerEl.value;
  if (!el) return;
  el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
}

// Watch for content changes (streaming deltas)
watch(
  () => props.messages.map((m) => m.content).join(""),
  scrollToBottom
);

// Force scroll on new message arrival
watch(
  () => props.messages.length,
  () => {
    shouldAutoScroll.value = true;
    scrollToBottom();
  }
);
</script>

<template>
  <div
    ref="containerEl"
    class="flex-1 overflow-y-auto overscroll-contain"
    @scroll="onScroll"
  >
    <div class="max-w-3xl mx-auto px-4 sm:px-6 py-6 space-y-5">

      <!-- Empty state -->
      <div
        v-if="!messages.length"
        class="flex flex-col items-center justify-center min-h-[60vh] gap-5 text-center"
      >
        <div class="w-14 h-14 rounded-2xl bg-brand-50 dark:bg-brand-900/20 border border-brand-100 dark:border-brand-800/30 flex items-center justify-center">
          <AppIcon name="book" class="w-7 h-7 text-brand-500 dark:text-brand-400" />
        </div>
        <div class="space-y-1.5">
          <p class="text-base font-semibold text-gray-800 dark:text-gray-200">
            Ask your vault
          </p>
          <p class="text-sm text-gray-400 dark:text-gray-500 max-w-sm leading-relaxed">
            The AI searches your Obsidian notes and answers directly from them — with source citations.
          </p>
        </div>
        <div class="flex flex-col gap-2 w-full max-w-xs">
          <div
            v-for="hint in ['What are my notes about?', 'Summarise my project notes', 'What did I write about...']"
            :key="hint"
            class="text-xs text-gray-400 dark:text-gray-600 bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg px-3 py-2 text-left font-mono"
          >
            {{ hint }}
          </div>
        </div>
      </div>

      <!-- Message list -->
      <TransitionGroup
        name="message"
        tag="div"
        class="space-y-5"
      >
        <ChatMessage
          v-for="msg in messages"
          :key="msg.id"
          :message="msg"
        />
      </TransitionGroup>

    </div>
  </div>
</template>

<style scoped>
.message-enter-active {
  transition: all 0.2s ease-out;
}
.message-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.message-enter-to {
  opacity: 1;
  transform: translateY(0);
}
</style>
