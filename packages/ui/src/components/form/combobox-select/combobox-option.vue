<script setup lang="ts">
import { inject } from 'vue'

const props = defineProps<{
  value: string | number
  label?: string
  active?: boolean
}>()

const selectOption = inject('selectOption') as (value: string | number) => void
const hide = inject('hide') as () => void
</script>

<template>
  <div
    v-bind="{ ...$attrs, class: null, style: null }"
    class="line-clamp-1 cursor-pointer overflow-hidden text-ellipsis whitespace-pre-wrap rounded px-2 py-1 text-xs text-$text-primary text-$text-primary transition-colors duration-150 ease-in-out will-change-background-color will-change-color hover:bg-$surface-1 hover:bg-$surface-2 sm:text-sm"
    :class="{ 'bg-$surface-1 bg-$surface-2': props.active }"
    @click="() => {
      selectOption(props.value)
      hide()
    }"
  >
    <slot>
      {{ props.label }}
    </slot>
  </div>
</template>
