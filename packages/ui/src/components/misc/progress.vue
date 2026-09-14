<script setup lang="ts">
defineProps<{
  progress: number
  barClass?: string
}>()
</script>

<template>
  <div relative overflow-hidden rounded-md>
    <div
      :class="[barClass ? barClass : 'bg-[var(--accent)]']"
      absolute h-4 min-w-2 rounded-md will-change-width
      :style="{ width: `${progress}%` }"
      transition="width duration-500 ease-in-out"
    >
      <div
        v-if="progress < 100"
        absolute inset-0 origin-left rounded-md bg-$surface-1
        class="progress-shine-animation"
      />
    </div>
    <div
      bg="[var(--surface-3)]" h-4 w-full rounded-md
    />
  </div>
</template>

<style scoped>
.progress-shine-animation {
  animation: progress-shine 2s cubic-bezier(0.35, 0.08, 0.04, 0.99) infinite;
  will-change: transform, opacity;
}

@keyframes progress-shine {
  0% {
    opacity: 0.4;
    transform: scale(0, 1);
  }
  100% {
    opacity: 0;
    transform: scale(1, 1);
  }
}
</style>
