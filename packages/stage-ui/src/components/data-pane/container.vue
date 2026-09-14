<script setup lang="ts">
import { Collapsible } from '@proj-aijade/ui'

withDefaults(defineProps<{
  title?: string
  icon?: string
  innerClass?: string
  expand?: boolean
}>(), {
  expand: true,
})
</script>

<template>
  <Collapsible :default="expand">
    <template #trigger="slotProps">
      <button
        class="w-full flex items-center justify-between rounded-lg px-2 py-1 outline-none transition-all duration-250 ease-in-out"
        text="$text-secondary"
        bg="$surface-1"
        hover="bg-$surface-1 bg-$surface-3"
        @click="slotProps.setVisible(!slotProps.visible)"
      >
        <slot name="title">
          <div flex items-center gap-1.5 text="xs 2xl:sm">
            <div v-if="icon" :class="icon" size-4 />
            {{ title }}
          </div>
        </slot>
        <div
          i-solar:alt-arrow-down-linear
          transition="transform duration-250"
          :class="{ 'rotate-180': slotProps.visible }"
        />
      </button>
    </template>
    <div gap="1" grid items-center p-1 :class="innerClass">
      <slot />
    </div>
  </Collapsible>
</template>
