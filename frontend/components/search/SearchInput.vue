<script setup lang="ts">
const props = defineProps<{
  modelValue: string;
  loading?: boolean;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: string];
  search: [query: string];
}>();

const inputEl = ref<HTMLInputElement | null>(null);

const inner = computed({
  get: () => props.modelValue,
  set: (v) => emit("update:modelValue", v),
});

function clear() {
  emit("update:modelValue", "");
  nextTick(() => inputEl.value?.focus());
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Enter") emit("search", props.modelValue);
  if (e.key === "Escape") clear();
}

onMounted(() => inputEl.value?.focus());
</script>

<template>
  <div class="relative">
    <!-- Left icon: spinner while loading, search icon otherwise -->
    <div class="absolute left-4 top-1/2 -translate-y-1/2 pointer-events-none">
      <svg
        v-if="loading"
        class="w-5 h-5 text-brand-500 animate-spin"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
      >
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" />
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
      </svg>
      <svg
        v-else
        class="w-5 h-5 text-gray-400 dark:text-gray-500"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        stroke-width="1.75"
      >
        <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
    </div>

    <input
      ref="inputEl"
      v-model="inner"
      type="text"
      placeholder="Search your vault by meaning, not just keywords…"
      :class="[
        'w-full pl-12 py-3.5 text-sm rounded-xl border transition-all duration-150',
        'bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100',
        'placeholder:text-gray-400 dark:placeholder:text-gray-500',
        'focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent',
        modelValue ? 'pr-10' : 'pr-4',
        'border-gray-200 dark:border-gray-700',
      ]"
      @keydown="onKeydown"
    />

    <!-- Clear button -->
    <Transition name="fade">
      <button
        v-if="modelValue"
        class="absolute right-3 top-1/2 -translate-y-1/2 w-6 h-6 rounded-md flex items-center justify-center text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
        title="Clear search"
        @click="clear"
      >
        <svg xmlns="http://www.w3.org/2000/svg" class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </Transition>
  </div>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.1s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
