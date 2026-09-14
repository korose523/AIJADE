<script setup lang="ts">
import type { BackgroundOption } from './types'

import { useResizeObserver, useScreenSafeArea } from '@vueuse/core'
import { DialogContent, DialogOverlay, DialogPortal, DialogRoot, DialogTitle, VisuallyHidden } from 'reka-ui'
import { DrawerContent, DrawerHandle, DrawerOverlay, DrawerPortal, DrawerRoot } from 'vaul-vue'
import { onMounted } from 'vue'

import BackgroundPicker from './background-picker.vue'

import { useBreakpoints } from '../../../../composables/use-breakpoints'

const props = defineProps<{
  options: BackgroundOption[]
}>()
const emit = defineEmits<{
  (e: 'apply', payload: { option: BackgroundOption, color?: string }): void
  (e: 'remove', option: BackgroundOption): void
}>()
const showDialog = defineModel({ type: Boolean, default: false, required: false })
const selected = defineModel<BackgroundOption | undefined>('selected', { default: undefined })

const { isDesktop } = useBreakpoints()
const screenSafeArea = useScreenSafeArea()

useResizeObserver(document.documentElement, () => screenSafeArea.update())
onMounted(() => screenSafeArea.update())
</script>

<template>
  <DialogRoot v-if="isDesktop" :open="showDialog" @update:open="value => showDialog = value">
    <DialogPortal>
      <DialogOverlay class="fixed inset-0 z-[9999] bg-$scrim backdrop-blur-sm data-[state=closed]:animate-fadeOut data-[state=open]:animate-fadeIn" />
      <DialogContent class="fixed left-1/2 top-1/2 z-[9999] max-h-[85vh] max-w-5xl w-[92dvw] flex flex-col transform overflow-hidden rounded-2xl bg-$surface-1 bg-$surface-1 p-6 shadow-xl outline-none backdrop-blur-md -translate-x-1/2 -translate-y-1/2 data-[state=closed]:animate-contentHide data-[state=open]:animate-contentShow">
        <VisuallyHidden>
          <DialogTitle>Background Picker</DialogTitle>
        </VisuallyHidden>
        <BackgroundPicker
          v-model="selected"
          :options="props.options"
          allow-upload
          class="min-h-0 flex-1"
          @apply="payload => { emit('apply', payload); showDialog = false }"
          @import="payload => emit('apply', payload)"
          @remove="option => emit('remove', option)"
        />
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
  <DrawerRoot v-else :open="showDialog" should-scale-background @update:open="value => showDialog = value">
    <DrawerPortal>
      <DrawerOverlay class="fixed inset-0" />
      <DrawerContent
        :class="[
          'fixed bottom-0 left-0 right-0 z-1000',
          'mt-20 px-4 pt-4',
          'flex flex-col',
          'h-full max-h-[85%]',
          'rounded-t-[32px] outline-none backdrop-blur-md',
          'bg-$surface-1 bg-$surface-1',
        ]"
        :style="{ paddingBottom: `${Math.max(Number.parseFloat(screenSafeArea.bottom.value.replace('px', '')), 24)}px` }"
      >
        <DrawerHandle
          :class="[
            '[div&]:bg-$surface-1 [div&]:bg-$surface-1',
          ]"
        />
        <BackgroundPicker
          v-model="selected"
          :options="props.options"
          allow-upload
          class="min-h-0 flex-1"
          @apply="payload => { emit('apply', payload); showDialog = false }"
          @import="payload => emit('apply', payload)"
          @remove="option => emit('remove', option)"
        />
      </DrawerContent>
    </DrawerPortal>
  </DrawerRoot>
</template>
