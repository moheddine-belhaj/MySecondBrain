<script setup lang="ts">
import { useTheme } from "~/composables/useTheme";

const { isDark, toggle } = useTheme();

const props = defineProps<{ title: string }>();
</script>

<template>
  <header class="flex items-center justify-between px-6 py-3 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
    <h1 class="text-base font-semibold text-gray-800 dark:text-gray-100">
      {{ props.title }}
    </h1>

    <div class="flex items-center gap-2">
      <!-- Theme toggle -->
      <button
        class="btn-ghost p-2 rounded-lg"
        :title="isDark ? 'Switch to light mode' : 'Switch to dark mode'"
        @click="toggle"
      >
        <span v-if="isDark" class="text-base">☀️</span>
        <span v-else class="text-base">🌙</span>
      </button>
    </div>
  </header>
</template>
