<script setup lang="ts">
import { useSlots } from 'vue'

import BasicInputFile from './basic-input-file.vue'

defineProps<{
  accept?: string
  multiple?: boolean
}>()

const slots = useSlots()
</script>

<template>
  <BasicInputFile
    :class="[
      'min-h-[120px] flex flex-col cursor-pointer items-center justify-center rounded-xl p-6',
      'border-dashed border-2',
      'transition-all duration-300',
      'opacity-95',
      'hover:scale-100 hover:opacity-100 hover:shadow-md hover:shadow-lg',
    ]"
    :is-not-dragging-classes="[
      'border-$hairline border-$hairline hover:border-primary-300 hover:border-primary-700',
      'bg-$surface-1 bg-$scrim hover:bg-$surface-1 hover:bg-$scrim',
    ]"
    :is-dragging-classes="[
      'border-primary-400 border-primary-600 hover:border-primary-300 hover:border-primary-700',
      'bg-primary-50/5 bg-primary-900/5',
    ]"
    :accept="accept"
    :multiple="multiple"
  >
    <template #default="{ isDragging }">
      <slot v-if="slots.default" :is-dragging="isDragging" />
      <div
        v-else
        class="flex flex-col items-center"
        :class="[
          isDragging ? 'text-primary-500 text-primary-400' : 'text-$text-muted text-$text-secondary',
        ]"
      >
        <div i-solar:upload-square-line-duotone mb-2 text-5xl />
        <p font-medium text="center lg">
          Upload
        </p>
        <p v-if="isDragging" text="center" text-sm>
          Release to upload
        </p>
        <p v-else text="center" text-sm>
          Click or drag and drop a file here
        </p>
      </div>
    </template>
  </BasicInputFile>
</template>
