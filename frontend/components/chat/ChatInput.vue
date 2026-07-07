<script setup lang="ts">
const emit = defineEmits<{
  send: [text: string];
}>();

const props = defineProps<{
  disabled?: boolean;
}>();

const text = ref("");
const textareaEl = ref<HTMLTextAreaElement | null>(null);
const MAX_CHARS = 4000;

const charsRemaining = computed(() => MAX_CHARS - text.value.length);
const isOverLimit = computed(() => text.value.length > MAX_CHARS);
const canSend = computed(
  () => text.value.trim().length > 0 && !props.disabled && !isOverLimit.value
);

function autoResize() {
  const el = textareaEl.value;
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
}

function send() {
  const t = text.value.trim();
  if (!t || !canSend.value) return;
  emit("send", t);
  text.value = "";
  nextTick(() => {
    if (textareaEl.value) {
      textareaEl.value.style.height = "auto";
      textareaEl.value.focus();
    }
  });
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
}

// Auto-focus on mount
onMounted(() => textareaEl.value?.focus());
</script>

<template>
  <div class="border-t border-gray-200 dark:border-gray-800 bg-white/90 dark:bg-gray-950/90 backdrop-blur-sm px-4 py-3">
    <div class="max-w-3xl mx-auto space-y-2">

      <!-- Input container -->
      <div
        :class="[
          'relative flex items-end gap-2 rounded-xl border bg-gray-50 dark:bg-gray-900',
          'transition-all duration-150',
          isOverLimit
            ? 'border-red-400 dark:border-red-600 ring-1 ring-red-400/20'
            : 'border-gray-200 dark:border-gray-700 focus-within:border-brand-400 dark:focus-within:border-brand-500 focus-within:ring-1 focus-within:ring-brand-400/20',
        ]"
      >
        <textarea
          ref="textareaEl"
          v-model="text"
          rows="1"
          :class="[
            'flex-1 resize-none bg-transparent px-4 py-3 text-sm leading-relaxed',
            'text-gray-800 dark:text-gray-200',
            'placeholder:text-gray-400 dark:placeholder:text-gray-500',
            'focus:outline-none max-h-48 min-h-[44px]',
          ]"
          placeholder="Ask your vault… (Enter to send, Shift+Enter for new line)"
          :disabled="disabled"
          @input="autoResize"
          @keydown="onKeydown"
        />

        <!-- Right controls -->
        <div class="flex items-center gap-1 pr-2 pb-2 shrink-0">
          <!-- Char counter (only near limit) -->
          <Transition name="fade">
            <span
              v-if="text.length > 3500"
              :class="[
                'text-[10px] tabular-nums font-mono transition-colors',
                isOverLimit ? 'text-red-500' : 'text-gray-400 dark:text-gray-500',
              ]"
            >
              {{ charsRemaining }}
            </span>
          </Transition>

          <!-- Send button -->
          <button
            :class="[
              'w-8 h-8 rounded-lg flex items-center justify-center transition-all duration-150',
              canSend
                ? 'bg-brand-600 text-white hover:bg-brand-700 shadow-sm'
                : 'bg-gray-100 dark:bg-gray-800 text-gray-300 dark:text-gray-600 cursor-not-allowed',
            ]"
            :disabled="!canSend"
            aria-label="Send message"
            @click="send"
          >
            <!-- Spinner while disabled + had content (loading state) -->
            <svg
              v-if="disabled && text.length === 0"
              class="w-4 h-4 animate-spin"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" />
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
            </svg>
            <!-- Send arrow -->
            <svg
              v-else
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="currentColor"
              class="w-4 h-4"
            >
              <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
            </svg>
          </button>
        </div>
      </div>

      <!-- Footer hints -->
      <div class="flex items-center justify-between px-1">
        <p class="text-[10px] text-gray-400 dark:text-gray-600">
          <kbd class="font-mono">Enter</kbd> send · <kbd class="font-mono">Shift+Enter</kbd> newline
        </p>
        <p class="text-[10px] text-gray-400 dark:text-gray-600 font-mono">
          qwen2.5 · Obsidian
        </p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
