<script setup lang="ts">
import { useUiStore } from "~/stores/ui";

const ui = useUiStore();
const route = useRoute();

onMounted(() => {
  ui.initTheme();
});

const pageTitle = computed(() => {
  const map: Record<string, string> = {
    "/": "Chat",
    "/search": "Search",
    "/settings": "Settings",
  };
  return map[route.path] ?? "Second Brain";
});
</script>

<template>
  <div class="flex h-screen overflow-hidden bg-gray-50 dark:bg-gray-950">
    <AppSidebar />

    <div class="flex flex-col flex-1 min-w-0">
      <AppHeader :title="pageTitle" />

      <main class="flex-1 overflow-y-auto">
        <slot />
      </main>
    </div>
  </div>
</template>
