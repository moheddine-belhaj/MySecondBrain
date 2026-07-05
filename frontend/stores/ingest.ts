import { defineStore } from "pinia";
import type { IngestStatus, ScanResponse } from "~/types";
import { ingestApi } from "~/services/api";

export const useIngestStore = defineStore("ingest", () => {
  const status = ref<IngestStatus | null>(null);
  const scanResult = ref<ScanResponse | null>(null);
  const isIngesting = ref(false);
  const isScanning = ref(false);
  const error = ref<string | null>(null);

  async function triggerIngest() {
    error.value = null;
    isIngesting.value = true;
    try {
      status.value = await ingestApi.triggerIngest();
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : "Ingest failed";
    } finally {
      isIngesting.value = false;
    }
  }

  async function scan() {
    error.value = null;
    isScanning.value = true;
    try {
      scanResult.value = await ingestApi.scan();
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : "Scan failed";
    } finally {
      isScanning.value = false;
    }
  }

  return { status, scanResult, isIngesting, isScanning, error, triggerIngest, scan };
});
