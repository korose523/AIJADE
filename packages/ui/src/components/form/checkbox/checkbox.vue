<script setup lang="ts">
import { SwitchRoot, SwitchThumb } from 'reka-ui'

const props = defineProps<{
  disabled?: boolean
}>()

const modelValue = defineModel<boolean>({ required: true })
</script>

<template>
  <SwitchRoot
    v-model="modelValue"
    :disabled="props.disabled"
    :class="[
      'duration-250 ease-in-out',
      'focus-within:outline-none',
      'flex',
      'is-interacting',
      'border-[var(--hairline)] data-[state=checked]:border-[var(--accent)] focus-within:border-[var(--accent)]',
      'data-[state=checked]:bg-[var(--accent)] data-[state=unchecked]:bg-[var(--surface-3)] data-[state=checked]:bg-[var(--accent)] data-[state=unchecked]:bg-[var(--surface-3)]',
      'data-[state=unchecked]:disabled:bg-[var(--surface-3)] data-[state=unchecked]:disabled:bg-[var(--surface-3)]',
      'data-[state=checked]:disabled:bg-[var(--accent)] data-[state=checked]:disabled:bg-[var(--accent)]',
      'relative h-7 w-12.5 rounded-full',
      'shadow-sm focus-within:shadow-none',
      props.disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
    ]"
  >
    <SwitchThumb
      :class="[
        'my-auto size-6',
        'flex items-center justify-center',
        'translate-x-0.5 data-[state=checked]:translate-x-full',
        'rounded-full bg-$surface-1 text-xs',
        'transition-transform duration-250 ease-in-out',
        'will-change-transform',
      ]"
    />
  </SwitchRoot>
</template>
