<script setup lang="ts">
import { useObjectUrl } from '@vueuse/core'
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  accept?: string
  multiple?: boolean
  placeholder?: string
}>(), {
  placeholder: 'Choose file',
  multiple: false,
})

const modelValue = defineModel<File[] | undefined>({ default: undefined })

const fileNames = computed(() => {
  const files = modelValue.value ?? []
  if (!files.length)
    return props.placeholder
  return files.map(file => file.name).join(', ')
})

const previewImageFile = computed(() => {
  const files = modelValue.value ?? []
  return files.find(file => file.type.startsWith('image/'))
})

const previewUrl = useObjectUrl(previewImageFile)

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files) {
    modelValue.value = undefined
    return
  }

  const files = Array.from(input.files)
  modelValue.value = files.length ? files : undefined

  // Allow re-selecting the same file.
  input.value = ''
}
</script>

<template>
  <label
    :class="[
      'w-full flex cursor-pointer items-center gap-2',
      'rounded-lg border-2 border-solid border-$hairline bg-$surface-1 px-2 py-1 shadow-sm',
      'transition-all duration-200 ease-in-out',
      'border-$hairline bg-$surface-1',
      'hover:border-primary-300/70 hover:border-primary-700/70',
    ]"
  >
    <input
      type="file"
      :accept="accept"
      :multiple="multiple"
      :class="[
        'hidden',
      ]"
      @change="onFileChange"
    >

    <div
      :class="[
        'i-solar:upload-square-line-duotone h-5 w-5 shrink-0 text-$text-secondary text-$text-muted',
      ]"
    />

    <div
      :class="[
        'min-w-0 flex-1 truncate text-sm text-$text-secondary text-$text-primary',
      ]"
      :title="fileNames"
    >
      {{ fileNames }}
    </div>

    <div
      v-if="previewUrl"
      :class="[
        'h-8 w-8 shrink-0 overflow-hidden rounded-md border border-$hairline bg-$surface-1',
        'border-$hairline bg-$surface-1',
      ]"
    >
      <img
        :src="previewUrl"
        alt="Preview"
        :class="[
          'h-full w-full object-cover',
        ]"
      >
    </div>
  </label>
</template>
