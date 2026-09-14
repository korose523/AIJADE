<script setup lang="ts">
import { useAppRuntime } from '../../composables/runtime'

defineProps<{
  title: string
  icon: string
}>()

const { platform } = useAppRuntime()
</script>

<template>
  <div
    class="titlebar-glass"
    w="100dvw"
    top="0"
    fixed z-100 w-full select-none py-2 pr-4 drag-region
    :class="[
      platform === 'macos' ? 'pl-20' : 'pl-4',
    ]"
  >
    <div flex drag-region>
      <div
        bg="hover:$surface-3"
        transition="all duration-200 ease-in-out"
        flex cursor-pointer select-none items-center gap-2 rounded-md px-1.5 py-0.5
      >
        <div :class="icon" select-none text="$accent" whitespace-nowrap class="icon-glow" />
        <div><span select-none whitespace-nowrap text-sm text="$text-primary">{{ title }}</span></div>
      </div>
      <div w-full drag-region />
      <div
        bg="hover:$surface-3"
        transition="all duration-200 ease-in-out"
        flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-0.5
      >
        <div i-solar:info-circle-bold text="$text-muted" whitespace-nowrap class="transition-colors hover:text-$accent" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.titlebar-glass {
  background: var(--surface-glass);
  backdrop-filter: blur(var(--surface-glass-blur, 14px));
  -webkit-backdrop-filter: blur(var(--surface-glass-blur, 14px));
  border-bottom: 1px solid var(--hairline);
  box-shadow: var(--shadow-panel);
}

.icon-glow {
  filter: drop-shadow(0 0 6px oklch(70% 0.15 202 / 0.45));
}
</style>
