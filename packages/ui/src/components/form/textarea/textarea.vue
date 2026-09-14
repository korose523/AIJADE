<script setup lang="ts">
import BasicTextarea from './basic-text-area.vue'

const modelValue = defineModel<string>({ default: '' })
</script>

<template>
  <BasicTextarea
    v-model="modelValue"
    :class="[
      'focus:border-primary-300 focus:border-primary-400/50 border-2 border-solid border-$hairline border-$hairline',
      'transition-all duration-200 ease-in-out',
      'text-disabled:$text-muted text-disabled:$text-secondary',
      'cursor-disabled:not-allowed',
      'w-full rounded-lg px-2 py-1 text-nowrap text-sm outline-none',
      'shadow-sm',
      'bg-$surface-1 bg-$surface-1 focus:bg-$surface-1 focus:bg-$surface-1',
    ]"
  />
</template>
