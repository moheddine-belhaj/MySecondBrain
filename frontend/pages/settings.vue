<script setup lang="ts">
import { useIngestStore } from "~/stores/ingest";
import { useTheme } from "~/composables/useTheme";
import { useHealth } from "~/composables/useHealth";
import { storeToRefs } from "pinia";
import type { Theme } from "~/types";

definePageMeta({ layout: "default" });

const ingest = useIngestStore();
const { status, scanResult, isIngesting, isScanning, error: ingestError } = storeToRefs(ingest);

const { theme, isDark, set: setTheme } = useTheme();
const { health, isLoading: healthLoading, isHealthy, check: checkHealth } = useHealth();

onMounted(checkHealth);

const themes: { label: string; value: Theme }[] = [
  { label: "Light", value: "light" },
  { label: "Dark", value: "dark" },
  { label: "System", value: "system" },
];
</script>

<template>
  <div class="max-w-2xl mx-auto px-6 py-6 space-y-8">

    <!-- Backend health -->
    <section class="card p-5 space-y-3">
      <h2 class="text-sm font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-2">
        <AppIcon name="database" class="w-4 h-4" />
        Backend Status
      </h2>

      <div v-if="healthLoading" class="text-sm text-gray-400 dark:text-gray-500">Checking…</div>

      <div v-else-if="health" class="space-y-2">
        <div class="flex items-center gap-2">
          <span
            :class="[
              'w-2 h-2 rounded-full',
              isHealthy ? 'bg-green-500' : 'bg-red-500',
            ]"
          />
          <span class="text-sm font-medium" :class="isHealthy ? 'text-green-600 dark:text-green-400' : 'text-red-500'">
            {{ isHealthy ? 'All systems operational' : 'Degraded' }}
          </span>
        </div>

        <div class="grid grid-cols-2 gap-2">
          <div
            v-for="(componentStatus, name) in health.components"
            :key="name"
            class="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400"
          >
            <span
              :class="[
                'w-1.5 h-1.5 rounded-full shrink-0',
                componentStatus === 'ok' ? 'bg-green-500' : 'bg-yellow-500',
              ]"
            />
            <span class="capitalize">{{ name }}</span>
          </div>
        </div>
      </div>

      <button class="btn-ghost text-xs" @click="checkHealth">
        <AppIcon name="refresh" class="w-3.5 h-3.5" />
        Refresh
      </button>
    </section>

    <!-- Vault ingest -->
    <section class="card p-5 space-y-4">
      <h2 class="text-sm font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-2">
        <AppIcon name="upload" class="w-4 h-4" />
        Vault Ingest
      </h2>

      <p class="text-xs text-gray-500 dark:text-gray-400">
        Re-index your Obsidian vault so the AI picks up new or changed notes.
      </p>

      <div class="flex gap-2">
        <button class="btn-primary text-sm" :disabled="isIngesting" @click="ingest.triggerIngest">
          <AppIcon name="upload" class="w-4 h-4" />
          {{ isIngesting ? 'Ingesting…' : 'Ingest Vault' }}
        </button>

        <button class="btn-ghost text-sm" :disabled="isScanning" @click="ingest.scan">
          <AppIcon name="search" class="w-4 h-4" />
          {{ isScanning ? 'Scanning…' : 'Scan Vault' }}
        </button>
      </div>

      <p v-if="ingestError" class="text-xs text-red-500 dark:text-red-400">{{ ingestError }}</p>

      <!-- Ingest status -->
      <div v-if="status" class="text-xs text-gray-600 dark:text-gray-400 space-y-1">
        <div class="flex items-center gap-2">
          <AppIcon name="check" class="w-3.5 h-3.5 text-green-500" />
          Status: <span class="font-medium capitalize">{{ status.status }}</span>
        </div>
        <div>Notes processed: {{ status.processed_notes }} / {{ status.total_notes }}</div>
        <div v-if="status.message">{{ status.message }}</div>
      </div>

      <!-- Scan result -->
      <div v-if="scanResult" class="text-xs space-y-1">
        <p class="text-gray-500 dark:text-gray-400">
          Found {{ scanResult.total_notes }} note{{ scanResult.total_notes !== 1 ? 's' : '' }} in
          <code class="font-mono text-brand-600 dark:text-brand-400">{{ scanResult.vault_path }}</code>
        </p>
        <ul class="max-h-40 overflow-y-auto space-y-0.5 font-mono text-gray-400 dark:text-gray-500">
          <li v-for="note in scanResult.notes" :key="note" class="truncate">{{ note }}</li>
        </ul>
      </div>
    </section>

    <!-- Theme -->
    <section class="card p-5 space-y-4">
      <h2 class="text-sm font-semibold text-gray-700 dark:text-gray-300">Appearance</h2>

      <div class="flex gap-2">
        <button
          v-for="t in themes"
          :key="t.value"
          :class="[
            'btn text-sm',
            theme === t.value
              ? 'btn-primary'
              : 'btn-ghost border border-gray-200 dark:border-gray-700',
          ]"
          @click="setTheme(t.value)"
        >
          {{ t.label }}
        </button>
      </div>

      <p class="text-xs text-gray-400 dark:text-gray-500">
        Current: <span class="font-medium">{{ isDark ? 'Dark' : 'Light' }}</span>
      </p>
    </section>

  </div>
</template>
