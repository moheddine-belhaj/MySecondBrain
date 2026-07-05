<script setup lang="ts">
import { useSearchStore } from "~/stores/search";
import { storeToRefs } from "pinia";

definePageMeta({ layout: "default" });

const store = useSearchStore();
const { query, results, total, isLoading, error } = storeToRefs(store);

const q = ref("");
const topK = ref(5);

async function doSearch() {
  if (!q.value.trim()) return;
  await store.search(q.value, topK.value);
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Enter") doSearch();
}
</script>

<template>
  <div class="max-w-3xl mx-auto px-6 py-6 space-y-6">

    <!-- Search bar -->
    <div class="flex gap-2">
      <input
        v-model="q"
        type="text"
        class="input flex-1"
        placeholder="Search your vault..."
        :disabled="isLoading"
        @keydown="onKeydown"
      />
      <select v-model="topK" class="input w-20">
        <option :value="3">Top 3</option>
        <option :value="5">Top 5</option>
        <option :value="10">Top 10</option>
      </select>
      <button class="btn-primary" :disabled="!q.trim() || isLoading" @click="doSearch">
        <AppIcon name="search" class="w-4 h-4" />
        Search
      </button>
    </div>

    <!-- Error -->
    <p v-if="error" class="text-sm text-red-500 dark:text-red-400">{{ error }}</p>

    <!-- Loading -->
    <div v-if="isLoading" class="text-center py-12 text-gray-400 dark:text-gray-500 text-sm">
      Searching…
    </div>

    <!-- Results -->
    <div v-else-if="results.length" class="space-y-4">
      <p class="text-xs text-gray-500 dark:text-gray-400">
        {{ total }} result{{ total !== 1 ? 's' : '' }} for "<strong>{{ query }}</strong>"
      </p>

      <div v-for="chunk in results" :key="`${chunk.note_path}-${chunk.chunk_index}`" class="card p-4 space-y-2">
        <div class="flex items-start justify-between gap-3">
          <div>
            <p class="text-sm font-semibold text-gray-800 dark:text-gray-100">{{ chunk.note_title }}</p>
            <p class="text-xs text-gray-400 dark:text-gray-500 font-mono">{{ chunk.note_path }}</p>
          </div>
          <span class="shrink-0 text-xs font-medium px-2 py-0.5 rounded-full bg-brand-50 dark:bg-brand-900/30 text-brand-700 dark:text-brand-300">
            {{ (chunk.score * 100).toFixed(0) }}%
          </span>
        </div>

        <p v-if="chunk.heading_path.length" class="text-xs text-gray-400 dark:text-gray-500">
          {{ chunk.heading_path.join(' › ') }}
        </p>

        <p class="text-sm text-gray-700 dark:text-gray-300 leading-relaxed whitespace-pre-wrap">
          {{ chunk.chunk_text }}
        </p>

        <div class="flex flex-wrap gap-1 pt-1">
          <span
            v-for="tag in chunk.tags"
            :key="tag"
            class="text-xs px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400"
          >
            #{{ tag }}
          </span>
        </div>
      </div>
    </div>

    <!-- Empty -->
    <div v-else-if="query && !isLoading" class="text-center py-12 text-gray-400 dark:text-gray-500 text-sm">
      No results for "{{ query }}"
    </div>

    <!-- Initial state -->
    <div v-else class="text-center py-16 space-y-2">
      <AppIcon name="search" class="w-10 h-10 mx-auto text-gray-300 dark:text-gray-700" />
      <p class="text-sm text-gray-400 dark:text-gray-500">Search across all your notes by semantic similarity</p>
    </div>

  </div>
</template>
