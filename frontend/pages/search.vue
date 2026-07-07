<script setup lang="ts">
import { watchDebounced } from "@vueuse/core";
import { useSearchStore } from "~/stores/search";
import { storeToRefs } from "pinia";

definePageMeta({ layout: "default" });

const store = useSearchStore();
const {
  query,
  results,
  totalCandidates,
  latencyMs,
  isLoading,
  error,
  topK,
  scoreThreshold,
  activeTags,
  availableTags,
  hasActiveFilters,
  activeFilterCount,
} = storeToRefs(store);

// Local input text — drives debounced search
const inputText = ref(query.value);
const hasSearched = ref(false);
const showMobileFilters = ref(false);

// Instant search: fires 350ms after the user stops typing
watchDebounced(
  inputText,
  (val) => {
    if (val.trim().length >= 2) {
      store.search(val);
      hasSearched.value = true;
    } else if (!val.trim()) {
      store.clear();
      hasSearched.value = false;
    }
  },
  { debounce: 350 }
);

// Re-search when filters change (if a query is active)
watch(topK, () => { if (query.value) store.search(); });
watch(scoreThreshold, () => { if (query.value) store.search(); });
watch(activeTags, () => { if (query.value) store.search(); }, { deep: true });

function immediateSearch(q: string) {
  if (!q.trim()) return;
  store.search(q);
  hasSearched.value = true;
}
</script>

<template>
  <div class="flex flex-col h-full overflow-hidden">

    <!-- Sticky search bar -->
    <div
      class="px-4 sm:px-6 py-4 border-b border-gray-200 dark:border-gray-800
             bg-white/95 dark:bg-gray-950/95 backdrop-blur-sm shrink-0"
    >
      <div class="max-w-5xl mx-auto">
        <SearchInput
          v-model="inputText"
          :loading="isLoading"
          @search="immediateSearch"
        />
      </div>
    </div>

    <!-- Body -->
    <div class="flex-1 flex overflow-hidden">

      <!-- Desktop filters sidebar -->
      <aside
        class="hidden lg:flex flex-col shrink-0 w-60 xl:w-64 overflow-y-auto
               border-r border-gray-200 dark:border-gray-800
               bg-gray-50/50 dark:bg-gray-900/30 px-4 py-5"
      >
        <SearchFilters
          :top-k="topK"
          :score-threshold="scoreThreshold"
          :active-tags="activeTags"
          :available-tags="availableTags"
          :has-active="hasActiveFilters"
          :active-count="activeFilterCount"
          :disabled="isLoading"
          @update:top-k="topK = $event"
          @update:score-threshold="scoreThreshold = $event"
          @toggle-tag="store.toggleTag($event)"
          @clear="store.clearFilters()"
        />
      </aside>

      <!-- Results area -->
      <main class="flex-1 overflow-y-auto">
        <div class="max-w-3xl mx-auto px-4 sm:px-6 py-5">

          <!-- Mobile: filter toggle bar -->
          <div class="flex items-center justify-between mb-4 lg:hidden">
            <p class="text-xs text-gray-500 dark:text-gray-400">
              <span v-if="results.length">{{ results.length }} result{{ results.length !== 1 ? "s" : "" }}</span>
              <span v-else-if="!hasSearched">Semantic search</span>
            </p>
            <button
              class="btn-ghost text-xs h-8 px-3 gap-1.5"
              @click="showMobileFilters = !showMobileFilters"
            >
              <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.75">
                <path stroke-linecap="round" stroke-linejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2a1 1 0 01-.293.707L13 13.414V19a1 1 0 01-.553.894l-4 2A1 1 0 017 21v-7.586L3.293 6.707A1 1 0 013 6V4z" />
              </svg>
              Filters
              <span
                v-if="activeFilterCount > 0"
                class="inline-flex items-center justify-center w-4 h-4 rounded-full
                       bg-brand-600 text-white text-[10px] font-medium"
              >
                {{ activeFilterCount }}
              </span>
            </button>
          </div>

          <!-- Mobile filter panel -->
          <Transition name="slide-down">
            <div
              v-if="showMobileFilters"
              class="lg:hidden mb-5 p-4 bg-gray-50 dark:bg-gray-900 rounded-xl
                     border border-gray-200 dark:border-gray-800"
            >
              <SearchFilters
                :top-k="topK"
                :score-threshold="scoreThreshold"
                :active-tags="activeTags"
                :available-tags="availableTags"
                :has-active="hasActiveFilters"
                :active-count="activeFilterCount"
                :disabled="isLoading"
                @update:top-k="topK = $event"
                @update:score-threshold="scoreThreshold = $event"
                @toggle-tag="store.toggleTag($event)"
                @clear="store.clearFilters()"
              />
            </div>
          </Transition>

          <!-- Results -->
          <SearchResults
            :results="results"
            :query="query"
            :is-loading="isLoading"
            :error="error"
            :total="totalCandidates"
            :latency-ms="latencyMs"
            :has-searched="hasSearched"
          />
        </div>
      </main>
    </div>
  </div>
</template>

<style scoped>
.slide-down-enter-active,
.slide-down-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}
.slide-down-enter-from,
.slide-down-leave-to {
  opacity: 0;
  max-height: 0;
}
.slide-down-enter-to,
.slide-down-leave-from {
  opacity: 1;
  max-height: 500px;
}
</style>
