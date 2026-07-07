<script setup lang="ts">
const props = defineProps<{
  topK: number;
  scoreThreshold: number;
  activeTags: string[];
  availableTags: string[];
  hasActive: boolean;
  activeCount: number;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  "update:topK": [v: number];
  "update:scoreThreshold": [v: number];
  "toggle-tag": [tag: string];
  clear: [];
}>();

const TOP_K_OPTIONS = [3, 5, 10, 20] as const;

// Convert float threshold (0-1) to integer slider value (0-95)
const sliderValue = computed({
  get: () => Math.round(props.scoreThreshold * 100),
  set: (v: number) => emit("update:scoreThreshold", v / 100),
});

const thresholdLabel = computed(() =>
  props.scoreThreshold === 0 ? "Any score" : `≥ ${Math.round(props.scoreThreshold * 100)}%`
);
</script>

<template>
  <div class="space-y-5">
    <!-- Header row -->
    <div class="flex items-center justify-between">
      <h3 class="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">
        Filters
      </h3>
      <button
        v-if="hasActive"
        class="text-xs text-brand-500 hover:text-brand-600 dark:text-brand-400 dark:hover:text-brand-300 transition-colors"
        @click="emit('clear')"
      >
        Clear all
      </button>
    </div>

    <!-- Results count -->
    <div>
      <p class="text-xs font-medium text-gray-600 dark:text-gray-400 mb-2">Results</p>
      <div class="flex gap-1.5 flex-wrap">
        <button
          v-for="k in TOP_K_OPTIONS"
          :key="k"
          :disabled="disabled"
          :class="[
            'px-3 py-1 text-xs rounded-lg border font-medium transition-all duration-100',
            topK === k
              ? 'bg-brand-600 text-white border-brand-600 dark:bg-brand-600 dark:border-brand-600'
              : 'bg-white dark:bg-gray-900 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-700 hover:border-brand-300 dark:hover:border-brand-700',
            disabled ? 'opacity-40 cursor-not-allowed' : '',
          ]"
          @click="emit('update:topK', k)"
        >
          Top {{ k }}
        </button>
      </div>
    </div>

    <!-- Score threshold -->
    <div>
      <div class="flex items-center justify-between mb-2">
        <p class="text-xs font-medium text-gray-600 dark:text-gray-400">Min score</p>
        <span
          :class="[
            'text-xs font-mono font-medium',
            scoreThreshold > 0 ? 'text-brand-600 dark:text-brand-400' : 'text-gray-400 dark:text-gray-500',
          ]"
        >
          {{ thresholdLabel }}
        </span>
      </div>
      <input
        v-model.number="sliderValue"
        type="range"
        min="0"
        max="95"
        step="5"
        :disabled="disabled"
        class="w-full h-1.5 rounded-full appearance-none cursor-pointer
          bg-gray-200 dark:bg-gray-700
          accent-brand-600 dark:accent-brand-400
          disabled:opacity-40 disabled:cursor-not-allowed"
        @change="emit('update:scoreThreshold', sliderValue / 100)"
      />
      <div class="flex justify-between text-[10px] text-gray-300 dark:text-gray-600 mt-1 font-mono">
        <span>0%</span>
        <span>95%</span>
      </div>
    </div>

    <!-- Tag filter -->
    <Transition name="fade">
      <div v-if="availableTags.length > 0">
        <p class="text-xs font-medium text-gray-600 dark:text-gray-400 mb-2">
          Tags
          <span class="text-gray-400 dark:text-gray-600 font-normal">(from results)</span>
        </p>
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="tag in availableTags"
            :key="tag"
            :disabled="disabled"
            :class="[
              'flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-mono transition-all duration-100',
              activeTags.includes(tag)
                ? 'bg-brand-600 text-white'
                : 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700',
              disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer',
            ]"
            @click="emit('toggle-tag', tag)"
          >
            <span class="opacity-60">#</span>{{ tag }}
          </button>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
