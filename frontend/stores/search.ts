import { defineStore } from "pinia";
import type { RetrievedChunk } from "~/types";
import { searchApi } from "~/services/api";

export const useSearchStore = defineStore("search", () => {
  const query = ref("");
  const results = ref<RetrievedChunk[]>([]);
  const totalCandidates = ref(0);
  const deduplicatedCount = ref(0);
  const latencyMs = ref<number | null>(null);
  const filtersApplied = ref(false);
  const isLoading = ref(false);
  const error = ref<string | null>(null);

  // Filters
  const topK = ref(5);
  const scoreThreshold = ref(0); // 0 = no minimum
  const activeTags = ref<string[]>([]);

  const availableTags = computed(() => {
    const tagSet = new Set<string>();
    for (const chunk of results.value) {
      for (const tag of chunk.tags) tagSet.add(tag);
    }
    return [...tagSet].sort();
  });

  const hasActiveFilters = computed(
    () => topK.value !== 5 || scoreThreshold.value > 0 || activeTags.value.length > 0
  );

  const activeFilterCount = computed(() => {
    let n = 0;
    if (topK.value !== 5) n++;
    if (scoreThreshold.value > 0) n++;
    if (activeTags.value.length > 0) n++;
    return n;
  });

  async function search(q?: string) {
    const searchQ = (q !== undefined ? q : query.value).trim();
    if (!searchQ) return;
    query.value = searchQ;
    error.value = null;
    isLoading.value = true;

    try {
      const res = await searchApi.search(searchQ, {
        topK: topK.value,
        scoreThreshold: scoreThreshold.value > 0 ? scoreThreshold.value : undefined,
        tags: activeTags.value.length > 0 ? activeTags.value : undefined,
      });
      results.value = res.results;
      totalCandidates.value = res.total_candidates;
      deduplicatedCount.value = res.deduplicated_count;
      latencyMs.value = res.latency_ms;
      filtersApplied.value = res.filters_applied;
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : "Search failed";
      results.value = [];
      totalCandidates.value = 0;
    } finally {
      isLoading.value = false;
    }
  }

  function toggleTag(tag: string) {
    const idx = activeTags.value.indexOf(tag);
    if (idx >= 0) activeTags.value.splice(idx, 1);
    else activeTags.value.push(tag);
  }

  function clearFilters() {
    topK.value = 5;
    scoreThreshold.value = 0;
    activeTags.value = [];
  }

  function clear() {
    query.value = "";
    results.value = [];
    totalCandidates.value = 0;
    deduplicatedCount.value = 0;
    latencyMs.value = null;
    filtersApplied.value = false;
    error.value = null;
    clearFilters();
  }

  return {
    query,
    results,
    totalCandidates,
    deduplicatedCount,
    latencyMs,
    filtersApplied,
    isLoading,
    error,
    topK,
    scoreThreshold,
    activeTags,
    availableTags,
    hasActiveFilters,
    activeFilterCount,
    search,
    toggleTag,
    clearFilters,
    clear,
  };
});
