<script setup lang="ts">
defineProps<{
  title?: string
  description?: string
  onReset?: () => void
}>()
</script>

<template>
  <div flex="~ col gap-6">
    <div flex="~ row" items-center justify-between>
      <div>
        <h2 class="text-lg text-$text-muted text-$text-secondary md:text-2xl">
          {{ title || 'Basic' }}
        </h2>
        <div text="neutral-400 neutral-500">
          <span>{{ description || 'Essential settings' }}</span>
        </div>
      </div>
      <button
        v-if="onReset"
        title="Reset settings"
        flex items-center justify-center rounded-full p-2
        transition="all duration-250 ease-in-out"
        text="neutral-500 neutral-400"
        bg="transparent transparent hover:neutral-200 hover:neutral-800 active:neutral-300 active:neutral-700"
        @click="onReset"
      >
        <div i-solar:refresh-bold-duotone text-xl />
      </button>
    </div>
    <slot />
  </div>
</template>
