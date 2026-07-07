<script setup lang="ts">
import type { UiChatMessage } from "~/types";

const props = defineProps<{ message: UiChatMessage }>();

const isUser = computed(() => props.message.role === "user");

const time = computed(() =>
  new Date(props.message.createdAt).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  })
);

// Copy button state
const copied = ref(false);
function copyContent() {
  if (!props.message.content) return;
  navigator.clipboard.writeText(props.message.content);
  copied.value = true;
  setTimeout(() => (copied.value = false), 2000);
}
</script>

<template>
  <div
    :class="[
      'group flex items-start gap-3',
      isUser ? 'flex-row-reverse' : 'flex-row',
    ]"
  >
    <!-- Avatar -->
    <div
      :class="[
        'w-7 h-7 rounded-lg flex items-center justify-center text-[11px] font-semibold shrink-0 mt-0.5 select-none ring-1',
        isUser
          ? 'bg-brand-600 text-white ring-brand-700/30'
          : 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 ring-gray-200 dark:ring-gray-700',
      ]"
    >
      <span v-if="isUser">U</span>
      <!-- AI glyph -->
      <svg v-else viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
        <path d="M10 2a8 8 0 100 16A8 8 0 0010 2zm0 2a6 6 0 110 12A6 6 0 0110 4zm-.25 3a.75.75 0 000 1.5h.5a.75.75 0 000-1.5h-.5zM9 10.25a.75.75 0 01.75-.75h.5a.75.75 0 01.75.75v3a.75.75 0 01-1.5 0v-3A.75.75 0 019 10.25z"/>
      </svg>
    </div>

    <!-- Bubble + actions -->
    <div
      :class="[
        'flex flex-col gap-1 min-w-0',
        isUser ? 'items-end' : 'items-start',
      ]"
    >
      <!-- Bubble -->
      <div
        :class="[
          'rounded-2xl px-4 py-3 max-w-[78ch] min-w-[3rem]',
          isUser
            ? 'bg-brand-600 text-white rounded-tr-sm'
            : 'bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 text-gray-800 dark:text-gray-200 rounded-tl-sm shadow-sm',
        ]"
      >
        <!-- Typing indicator — before first delta arrives -->
        <TypingIndicator v-if="message.isStreaming && !message.content" />

        <!-- Error state -->
        <div v-else-if="message.error" class="flex items-center gap-2 text-sm text-red-500 dark:text-red-400">
          <AppIcon name="alert" class="w-4 h-4 shrink-0" />
          <span>{{ message.error }}</span>
        </div>

        <!-- Main content -->
        <ChatMessageContent
          v-else
          :content="message.content"
          :is-user="isUser"
          :is-streaming="message.isStreaming"
        />

        <!-- Sources -->
        <ChatSources
          v-if="!isUser && message.sources && message.sources.length > 0"
          :sources="message.sources"
        />
      </div>

      <!-- Meta row: timestamp + copy button -->
      <div
        :class="[
          'flex items-center gap-2 px-1 opacity-0 group-hover:opacity-100 transition-opacity duration-150',
          isUser ? 'flex-row-reverse' : 'flex-row',
        ]"
      >
        <span class="text-[10px] text-gray-400 dark:text-gray-600 tabular-nums">{{ time }}</span>

        <!-- Copy button (assistant only) -->
        <button
          v-if="!isUser && message.content && !message.isStreaming"
          class="text-[10px] flex items-center gap-1 text-gray-400 dark:text-gray-600
                 hover:text-gray-600 dark:hover:text-gray-400 transition-colors"
          :title="copied ? 'Copied!' : 'Copy'"
          @click="copyContent"
        >
          <AppIcon :name="copied ? 'check' : 'copy'" class="w-3 h-3" />
          {{ copied ? "Copied" : "Copy" }}
        </button>
      </div>
    </div>
  </div>
</template>
