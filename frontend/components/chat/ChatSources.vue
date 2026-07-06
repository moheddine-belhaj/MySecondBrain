<script setup lang="ts">
import type { NoteSource } from "~/types";

const props = defineProps<{ sources: NoteSource[] }>();
const open = ref(false);
</script>

<template>
  <div class="mt-3 pt-3 border-t border-gray-100 dark:border-gray-800">
    <!-- Toggle button -->
    <button
      class="group flex items-center gap-1.5 text-xs text-gray-400 dark:text-gray-500
             hover:text-gray-600 dark:hover:text-gray-300 transition-colors duration-150"
      @click="open = !open"
    >
      <AppIcon
        :name="open ? 'chevron-down' : 'chevron-right'"
        class="w-3 h-3 transition-transform duration-150"
      />
      <span>
        {{ sources.length }} source{{ sources.length !== 1 ? "s" : "" }}
      </span>
    </button>

    <!-- Source cards -->
    <Transition
      enter-active-class="transition-all duration-200 ease-out"
      enter-from-class="opacity-0 -translate-y-1"
      enter-to-class="opacity-100 translate-y-0"
      leave-active-class="transition-all duration-150 ease-in"
      leave-from-class="opacity-100 translate-y-0"
      leave-to-class="opacity-0 -translate-y-1"
    >
      <div v-if="open" class="mt-2 space-y-2">
        <div
          v-for="(src, i) in sources"
          :key="src.note_path"
          class="rounded-lg bg-gray-50 dark:bg-gray-800/60 border border-gray-200 dark:border-gray-700/60 p-3 space-y-1.5"
        >
          <!-- Title + score -->
          <div class="flex items-start justify-between gap-3">
            <div class="flex items-center gap-1.5 min-w-0">
              <span class="text-[10px] font-mono font-medium text-gray-400 dark:text-gray-500 shrink-0">
                [{{ i + 1 }}]
              </span>
              <span class="text-xs font-medium text-gray-700 dark:text-gray-300 truncate">
                {{ src.note_title }}
              </span>
            </div>
            <!-- Score bar -->
            <div class="flex items-center gap-1.5 shrink-0">
              <div class="w-12 h-1 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
                <div
                  class="h-full rounded-full bg-brand-500 dark:bg-brand-400"
                  :style="{ width: `${(src.score * 100).toFixed(0)}%` }"
                />
              </div>
              <span class="text-[10px] font-mono text-brand-600 dark:text-brand-400">
                {{ (src.score * 100).toFixed(0) }}%
              </span>
            </div>
          </div>

          <!-- Note path -->
          <p class="text-[10px] font-mono text-gray-400 dark:text-gray-500 truncate">
            {{ src.note_path }}
          </p>

          <!-- Excerpt -->
          <p class="text-xs text-gray-600 dark:text-gray-400 leading-relaxed line-clamp-3">
            {{ src.excerpt }}
          </p>
        </div>
      </div>
    </Transition>
  </div>
</template>
