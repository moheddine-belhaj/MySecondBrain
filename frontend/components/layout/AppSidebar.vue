<script setup lang="ts">
import { useUiStore } from "~/stores/ui";

const ui = useUiStore();
const route = useRoute();

const nav = [
  { label: "Chat", to: "/", icon: "chat" },
  { label: "Search", to: "/search", icon: "search" },
  { label: "Settings", to: "/settings", icon: "settings" },
];

function isActive(to: string) {
  return route.path === to;
}
</script>

<template>
  <aside
    :class="[
      'flex flex-col h-full bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-800',
      'transition-all duration-200',
      ui.sidebarOpen ? 'w-56' : 'w-14',
    ]"
  >
    <!-- Logo -->
    <div class="flex items-center gap-3 px-4 py-4 border-b border-gray-200 dark:border-gray-800">
      <span class="text-brand-600 dark:text-brand-400 text-xl font-bold shrink-0">🧠</span>
      <span v-if="ui.sidebarOpen" class="text-sm font-semibold text-gray-800 dark:text-gray-100 truncate">
        Second Brain
      </span>
    </div>

    <!-- Nav -->
    <nav class="flex-1 px-2 py-3 space-y-1">
      <NuxtLink
        v-for="item in nav"
        :key="item.to"
        :to="item.to"
        :class="[
          'flex items-center gap-3 rounded-lg px-2 py-2 text-sm font-medium transition-colors duration-150',
          isActive(item.to)
            ? 'bg-brand-50 dark:bg-brand-900/30 text-brand-700 dark:text-brand-300'
            : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-gray-100',
        ]"
      >
        <AppIcon :name="item.icon" class="w-5 h-5 shrink-0" />
        <span v-if="ui.sidebarOpen">{{ item.label }}</span>
      </NuxtLink>
    </nav>

    <!-- Collapse toggle -->
    <div class="px-2 py-3 border-t border-gray-200 dark:border-gray-800">
      <button
        class="btn-ghost w-full justify-center"
        :title="ui.sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'"
        @click="ui.toggleSidebar"
      >
        <AppIcon :name="ui.sidebarOpen ? 'chevron-left' : 'chevron-right'" class="w-4 h-4" />
      </button>
    </div>
  </aside>
</template>
