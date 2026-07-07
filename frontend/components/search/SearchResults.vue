<script setup lang="ts">
import type { RetrievedChunk } from "~/types";

defineProps<{
  results: RetrievedChunk[];
  query: string;
  isLoading: boolean;
  error: string | null;
  total: number;
  latencyMs: number | null;
  hasSearched: boolean;
}>();
</script>

<template>
  <div>
    <!-- Error -->
    <div
      v-if="error"
      class="flex items-center gap-2 px-4 py-3 rounded-xl bg-red-50 dark:bg-red-950/30
             border border-red-200 dark:border-red-800 text-sm text-red-600 dark:text-red-400"
    >
      <svg class="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.75">
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
      </svg>
      {{ error }}
    </div>

    <!-- Skeleton loading -->
    <div v-else-if="isLoading" class="space-y-3">
      <div
        v-for="i in 4"
        :key="i"
        class="card overflow-hidden animate-pulse"
      >
        <div class="h-0.5 bg-gray-100 dark:bg-gray-800" />
        <div class="p-4 space-y-3">
          <div class="flex items-start gap-3">
            <div class="w-6 h-6 rounded-md bg-gray-100 dark:bg-gray-800 shrink-0" />
            <div class="flex-1 space-y-2">
              <div class="h-3.5 bg-gray-100 dark:bg-gray-800 rounded w-3/5" />
              <div class="h-3 bg-gray-100 dark:bg-gray-800 rounded w-2/5" />
            </div>
            <div class="w-10 h-7 bg-gray-100 dark:bg-gray-800 rounded-lg shrink-0" />
          </div>
          <div class="space-y-1.5 pt-1">
            <div class="h-3 bg-gray-100 dark:bg-gray-800 rounded w-full" />
            <div class="h-3 bg-gray-100 dark:bg-gray-800 rounded w-full" />
            <div class="h-3 bg-gray-100 dark:bg-gray-800 rounded w-4/5" />
          </div>
        </div>
        <div class="h-9 bg-gray-50 dark:bg-gray-800/40 border-t border-gray-100 dark:border-gray-800" />
      </div>
    </div>

    <!-- Results -->
    <div v-else-if="results.length">
      <!-- Count header -->
      <div class="flex items-center justify-between mb-4">
        <p class="text-xs text-gray-500 dark:text-gray-400">
          <span class="font-semibold text-gray-700 dark:text-gray-300">{{ results.length }}</span>
          result{{ results.length !== 1 ? "s" : "" }}
          <span v-if="query"> for <span class="font-medium text-gray-700 dark:text-gray-300">"{{ query }}"</span></span>
          <span v-if="total > results.length" class="text-gray-400 dark:text-gray-500">
            · {{ total }} candidates
          </span>
        </p>
        <span v-if="latencyMs !== null" class="text-[11px] font-mono text-gray-300 dark:text-gray-600">
          {{ latencyMs.toFixed(0) }}ms
        </span>
      </div>

      <!-- Result cards -->
      <TransitionGroup name="results" tag="div" class="space-y-3">
        <SearchResult
          v-for="chunk in results"
          :key="`${chunk.note_path}-${chunk.chunk_index}`"
          :chunk="chunk"
          :query="query"
        />
      </TransitionGroup>
    </div>

    <!-- No results (after a search) -->
    <div
      v-else-if="hasSearched && !isLoading && query"
      class="flex flex-col items-center justify-center py-16 gap-4 text-center"
    >
      <div class="w-12 h-12 rounded-xl bg-gray-100 dark:bg-gray-800 flex items-center justify-center">
        <svg class="w-6 h-6 text-gray-300 dark:text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
      </div>
      <div class="space-y-1">
        <p class="text-sm font-medium text-gray-600 dark:text-gray-400">No results found</p>
        <p class="text-xs text-gray-400 dark:text-gray-500 max-w-xs">
          Try a broader query, lower the score threshold, or check that your vault has been indexed.
        </p>
      </div>
    </div>

    <!-- Initial empty state -->
    <div
      v-else-if="!hasSearched"
      class="flex flex-col items-center justify-center py-16 gap-5 text-center"
    >
      <div
        class="w-14 h-14 rounded-2xl bg-brand-50 dark:bg-brand-900/20
               border border-brand-100 dark:border-brand-800/30
               flex items-center justify-center"
      >
        <svg class="w-7 h-7 text-brand-500 dark:text-brand-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
      </div>
      <div class="space-y-2">
        <p class="text-sm font-semibold text-gray-700 dark:text-gray-300">Semantic search</p>
        <p class="text-xs text-gray-400 dark:text-gray-500 max-w-xs leading-relaxed">
          Finds notes by meaning, not just exact words. Ask a question or describe what you're looking for.
        </p>
      </div>
      <div class="flex flex-col gap-2 w-full max-w-xs text-left">
        <p
          v-for="hint in [
            'What did I write about machine learning?',
            'Notes on productivity and habits',
            'Ideas for my next project',
          ]"
          :key="hint"
          class="text-xs text-gray-400 dark:text-gray-500 bg-gray-50 dark:bg-gray-900
                 border border-gray-200 dark:border-gray-800 rounded-lg px-3 py-2 font-mono"
        >
          {{ hint }}
        </p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.results-enter-active { transition: all 0.15s ease-out; }
.results-enter-from { opacity: 0; transform: translateY(6px); }
</style>
