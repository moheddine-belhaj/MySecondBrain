<template>
  <div class="flex items-center gap-1 py-0.5 px-0.5" aria-label="Assistant is typing">
    <span
      v-for="i in 3"
      :key="i"
      class="w-1.5 h-1.5 rounded-full bg-gray-400 dark:bg-gray-500 animate-bounce"
      :style="{ animationDelay: `${(i - 1) * 160}ms`, animationDuration: '0.9s' }"
    />
  </div>
</template>
