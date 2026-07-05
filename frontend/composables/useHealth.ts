import type { HealthResponse } from "~/types";
import { healthApi } from "~/services/api";

export function useHealth() {
  const health = ref<HealthResponse | null>(null);
  const isLoading = ref(false);
  const error = ref<string | null>(null);

  async function check() {
    isLoading.value = true;
    error.value = null;
    try {
      health.value = await healthApi.check();
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : "Health check failed";
    } finally {
      isLoading.value = false;
    }
  }

  const isHealthy = computed(() => health.value?.status === "ok");

  return { health, isLoading, error, isHealthy, check };
}
