import { defineStore } from "pinia";
import type { RetrievedChunk } from "~/types";
import { searchApi } from "~/services/api";

export const useSearchStore = defineStore("search", () => {
  const query = ref("");
  const results = ref<RetrievedChunk[]>([]);
  const total = ref(0);
  const isLoading = ref(false);
  const error = ref<string | null>(null);

  async function search(q: string, topK = 5) {
    if (!q.trim()) return;
    error.value = null;
    isLoading.value = true;
    query.value = q;

    try {
      const res = await searchApi.search(q, topK);
      results.value = res.chunks;
      total.value = res.total;
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : "Search failed";
    } finally {
      isLoading.value = false;
    }
  }

  function clear() {
    query.value = "";
    results.value = [];
    total.value = 0;
    error.value = null;
  }

  return { query, results, total, isLoading, error, search, clear };
});
