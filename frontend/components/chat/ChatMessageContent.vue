<script setup lang="ts">
import { useMarkdown } from "~/composables/useMarkdown";

const props = defineProps<{
  content: string;
  isUser?: boolean;
  isStreaming?: boolean;
}>();

const { render } = useMarkdown();

// User messages: plain text (no markdown processing)
// Assistant messages: full markdown render
const rendered = computed(() => {
  if (props.isUser) return null;
  return render(props.content);
});
</script>

<template>
  <!-- User: plain text, no markdown -->
  <p v-if="isUser" class="text-sm leading-relaxed whitespace-pre-wrap break-words">
    {{ content }}
  </p>

  <!-- Assistant: rendered markdown + streaming cursor -->
  <div
    v-else
    :class="['prose-chat text-sm', isStreaming && content ? 'streaming-cursor' : '']"
    v-html="rendered"
  />
</template>
