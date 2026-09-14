<script setup lang="ts">
defineProps<{
  text: string
  description?: string
}>()
</script>

<template>
  <label
    class="w-full flex cursor-pointer items-center justify-between rounded-lg px-4 py-3 text-sm outline-none transition-all duration-250 ease-in-out"
    bg="neutral-50 neutral-800"
    hover="bg-$surface-1 bg-$surface-3"
  >
    <div>
      {{ $t(text) }}
      <div v-if="description" text="sm neutral-500">
        {{ $t(description) }}
      </div>
    </div>
    <slot />
  </label>
</template>
