<script setup lang="ts">
import type { RetrievedChunk } from "~/types";

const props = defineProps<{
  chunk: RetrievedChunk;
  query: string;
}>();

const PREVIEW_CHARS = 320;
const expanded = ref(false);

const needsExpand = computed(() => props.chunk.chunk_text.length > PREVIEW_CHARS);

const displayText = computed(() =>
  expanded.value || !needsExpand.value
    ? props.chunk.chunk_text
    : props.chunk.chunk_text.slice(0, PREVIEW_CHARS).trimEnd() + "…"
);

function highlightText(text: string, query: string): string {
  const escaped = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  if (!query.trim()) return escaped;

  const words = query
    .trim()
    .split(/\s+/)
    .filter((w) => w.length > 1)
    .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));

  if (!words.length) return escaped;

  const regex = new RegExp(`(${words.join("|")})`, "gi");
  return escaped.replace(
    regex,
    '<mark class="bg-yellow-200 dark:bg-yellow-900/60 text-current rounded-sm px-0.5">$1</mark>'
  );
}

const highlightedText = computed(() => highlightText(displayText.value, props.query));

function scoreBadgeClass(score: number) {
  if (score >= 0.8) return "text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800/40";
  if (score >= 0.6) return "text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800/40";
  if (score >= 0.4) return "text-orange-500 dark:text-orange-400 bg-orange-50 dark:bg-orange-900/20 border-orange-200 dark:border-orange-800/40";
  return "text-gray-400 dark:text-gray-500 bg-gray-50 dark:bg-gray-800/60 border-gray-200 dark:border-gray-700";
}

function scoreBarClass(score: number) {
  if (score >= 0.8) return "bg-emerald-500";
  if (score >= 0.6) return "bg-amber-400";
  if (score >= 0.4) return "bg-orange-400";
  return "bg-gray-300 dark:bg-gray-600";
}

const formattedDate = computed(() => {
  if (!props.chunk.note_modified_at) return null;
  return new Date(props.chunk.note_modified_at).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
});
</script>

<template>
  <article
    class="card overflow-hidden hover:border-brand-200 dark:hover:border-brand-800/60
           hover:shadow-md transition-all duration-150 group"
  >
    <!-- Score progress bar at top -->
    <div class="h-0.5 bg-gray-100 dark:bg-gray-800">
      <div
        :class="scoreBarClass(chunk.score)"
        :style="{ width: `${chunk.score * 100}%` }"
        class="h-full transition-all duration-500"
      />
    </div>

    <!-- Header -->
    <div class="flex items-start gap-3 px-4 pt-4 pb-3">
      <!-- Rank pill -->
      <span
        class="shrink-0 min-w-[1.5rem] h-6 rounded-md bg-gray-100 dark:bg-gray-800
               text-gray-400 dark:text-gray-500 text-xs font-mono font-semibold
               flex items-center justify-center mt-0.5 px-1"
      >
        {{ chunk.rank }}
      </span>

      <!-- Title + path -->
      <div class="flex-1 min-w-0">
        <h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate leading-snug">
          {{ chunk.note_title }}
        </h3>
        <p class="text-xs font-mono text-gray-400 dark:text-gray-500 truncate mt-0.5">
          {{ chunk.note_path }}
        </p>
      </div>

      <!-- Score badge -->
      <span
        :class="[
          'shrink-0 text-xs font-semibold font-mono px-2 py-1 rounded-lg border',
          scoreBadgeClass(chunk.score),
        ]"
      >
        {{ (chunk.score * 100).toFixed(0) }}%
      </span>
    </div>

    <!-- Heading breadcrumb -->
    <div v-if="chunk.heading_path.length" class="px-4 pb-2.5">
      <nav class="flex items-center gap-0.5 flex-wrap text-xs text-gray-400 dark:text-gray-500">
        <svg class="w-3 h-3 shrink-0 mr-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
        </svg>
        <template v-for="(heading, i) in chunk.heading_path" :key="i">
          <span class="truncate max-w-[140px] hover:text-gray-600 dark:hover:text-gray-300 transition-colors">
            {{ heading }}
          </span>
          <svg
            v-if="i < chunk.heading_path.length - 1"
            class="w-3 h-3 shrink-0 opacity-40"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            stroke-width="2"
          >
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </template>
      </nav>
    </div>

    <!-- Chunk text with highlighting -->
    <div class="px-4 pb-3">
      <p
        class="text-sm text-gray-700 dark:text-gray-300 leading-relaxed whitespace-pre-wrap break-words"
        v-html="highlightedText"
      />
      <button
        v-if="needsExpand"
        class="mt-2 text-xs text-brand-500 hover:text-brand-600
               dark:text-brand-400 dark:hover:text-brand-300
               transition-colors font-medium"
        @click="expanded = !expanded"
      >
        {{ expanded ? "Show less ↑" : "Show more ↓" }}
      </button>
    </div>

    <!-- Tags -->
    <div v-if="chunk.tags.length" class="flex flex-wrap gap-1.5 px-4 pb-3">
      <span
        v-for="tag in chunk.tags"
        :key="tag"
        class="text-xs px-1.5 py-0.5 rounded-md bg-gray-100 dark:bg-gray-800
               text-gray-500 dark:text-gray-400 font-mono"
      >
        #{{ tag }}
      </span>
    </div>

    <!-- Metadata footer -->
    <div
      class="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5
             border-t border-gray-100 dark:border-gray-800/60
             text-[11px] text-gray-400 dark:text-gray-500"
    >
      <span class="flex items-center gap-1">
        <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.75">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        {{ chunk.word_count }} words
      </span>
      <span class="font-mono">
        chunk {{ chunk.chunk_index + 1 }} / {{ chunk.total_chunks }}
      </span>
      <span v-if="formattedDate" class="ml-auto">
        {{ formattedDate }}
      </span>
    </div>
  </article>
</template>
