<script setup lang="ts" generic="T extends AcceptableValue">
import type { AcceptableValue } from 'reka-ui'

import {
  ComboboxAnchor,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxGroup,
  ComboboxInput,
  ComboboxItem,
  ComboboxItemIndicator,
  ComboboxLabel,
  ComboboxPortal,
  ComboboxRoot,
  ComboboxSeparator,
  ComboboxTrigger,
  ComboboxViewport,
} from 'reka-ui'
import { computed } from 'vue'

interface ComboboxOptionItem<T extends AcceptableValue> {
  label: string
  value: T
  description?: string
  disabled?: boolean
  icon?: string
}

interface ComboboxOptionGroupItem<T extends AcceptableValue> {
  groupLabel?: string
  children?: ComboboxOptionItem<T>[]
}

const props = withDefaults(defineProps<{
  options: ComboboxOptionItem<T>[] | ComboboxOptionGroupItem<T>[]
  placeholder?: string
  disabled?: boolean
  openOnClick?: boolean
  contentMinWidth?: string | number
  contentWidth?: string | number
}>(), {
  disabled: false,
  openOnClick: true,
})

const modelValue = defineModel<T>({ required: false })

const normalizedOptions = computed<ComboboxOptionGroupItem<T>[]>(() => {
  if (!props.options.length) {
    return []
  }

  const [firstOption] = props.options
  if ('value' in firstOption) {
    return [
      {
        groupLabel: '',
        children: props.options as ComboboxOptionItem<T>[],
      },
    ]
  }

  return props.options as ComboboxOptionGroupItem<T>[]
})

const flattenedOptions = computed<ComboboxOptionItem<T>[]>(() =>
  normalizedOptions.value.flatMap(group => group.children ?? []),
)

function toDisplayValue(value: T): string {
  const option = flattenedOptions.value.find(option => option.value === value)
  return option?.label ?? props.placeholder ?? ''
}

function toCssSize(value?: string | number): string | undefined {
  if (value == null) {
    return undefined
  }

  return typeof value === 'number' ? `${value}px` : value
}
</script>

<template>
  <ComboboxRoot
    v-model="modelValue"
    :disabled="props.disabled"
    :open-on-click="props.openOnClick"
    :class="['relative', 'w-full', 'h-fit']"
  >
    <ComboboxAnchor
      :class="[
        'w-full inline-flex items-center justify-between rounded-xl border px-3 leading-none h-9 gap-[5px] outline-none',
        'text-sm text-[var(--text-primary)] data-[placeholder]:text-[var(--text-muted)]',
        'bg-[var(--surface-1)] hover:bg-[var(--surface-2)] hover:bg-[var(--surface-3)]',
        'border border-solid border-[var(--hairline)] focus:border-[var(--accent)]',
        'shadow-[var(--shadow-panel)] focus:shadow-[0_0_0_2px_var(--accent)]',
        'transition-colors duration-200 ease-in-out',
        props.disabled ? 'cursor-not-allowed bg-[var(--surface-3)] opacity-60' : 'cursor-pointer',
      ]"
    >
      <ComboboxInput
        :class="[
          '!bg-transparent outline-none h-full selection:bg-grass5 placeholder:text-[var(--text-muted)] w-full',
          'text-[var(--text-primary)]',
          'transition-colors duration-200 ease-in-out',
        ]"
        :disabled="props.disabled"
        :placeholder="props.placeholder"
        :display-value="(val) => toDisplayValue(val)"
      />
      <ComboboxTrigger>
        <div
          i-solar:alt-arrow-down-linear
          :class="[
            'h-4 w-4',
            'text-[var(--text-secondary)]',
            'transition-colors duration-200 ease-in-out',
          ]"
        />
      </ComboboxTrigger>
    </ComboboxAnchor>

    <ComboboxPortal>
      <ComboboxContent
        position="popper"
        side="bottom"
        align="start"
        :side-offset="4"
        :avoid-collisions="true"
        :class="[
          // NOTICE: DialogContent/DialogOverlay use z-[9999], and DrawerContent uses z-[1000].
          // ComboboxContent must render above these layers so that dropdowns inside
          // Dialog/Drawer are not hidden behind the overlay or dismissed unexpectedly.
          // Read more at: https://github.com/moeru-ai/airi/issues/1136
          'z-[10010]',
          'w-full overflow-hidden rounded-xl will-change-[opacity,transform]',
          'data-[side=top]:animate-slideDownAndFade data-[side=right]:animate-slideLeftAndFade data-[side=bottom]:animate-slideUpAndFade data-[side=left]:animate-slideRightAndFade',
          'glass-panel',
          'focus:border-[var(--accent)]',
        ]"
        :style="{
          width: toCssSize(props.contentWidth) ?? 'var(--reka-combobox-trigger-width)',
          minWidth: toCssSize(props.contentMinWidth) ?? '160px',
        }"
      >
        <ComboboxViewport :class="['p-[2px]', 'max-h-50dvh', 'overflow-y-auto']">
          <ComboboxEmpty
            :class="[
              'font-medium py-2 px-2',
              'text-xs text-[var(--text-secondary)]',
              'transition-colors duration-200 ease-in-out',
            ]"
          >
            <slot name="empty" />
          </ComboboxEmpty>

          <template
            v-for="(group, groupIndex) in normalizedOptions"
            :key="group.groupLabel || `group-${groupIndex}`"
          >
            <ComboboxGroup :class="['overflow-x-hidden']">
              <ComboboxSeparator
                v-if="groupIndex !== 0"
                :class="['m-[5px]', 'h-[1px]', 'bg-[var(--hairline)]']"
              />

              <ComboboxLabel
                v-if="group.groupLabel"
                :class="[
                  'px-[25px] text-xs leading-[25px]',
                  'text-[var(--text-muted)]',
                  'transition-colors duration-200 ease-in-out',
                ]"
              >
                {{ group.groupLabel }}
              </ComboboxLabel>

              <ComboboxItem
                v-for="(option, optionIndex) in group.children || []"
                :key="`${group.groupLabel || groupIndex}-${option.label}-${optionIndex}`"
                :text-value="option.label"
                :value="option.value"
                :disabled="option.disabled"
                :class="[
                  'leading-normal rounded-lg grid grid-cols-[1rem_minmax(0,1fr)] items-center gap-2 min-h-8 px-2 relative select-none data-[disabled]:pointer-events-none data-[highlighted]:outline-none',
                  'data-[highlighted]:bg-[var(--accent-soft)] data-[highlighted]:bg-[var(--accent-soft)]',
                  'text-sm text-[var(--text-primary)] data-[disabled]:text-[var(--text-muted)] data-[disabled]:text-[var(--text-muted)] data-[highlighted]:text-[var(--accent-strong)]',
                  'transition-colors duration-200 ease-in-out',
                  option.disabled ? 'cursor-not-allowed' : 'cursor-pointer',
                ]"
              >
                <ComboboxItemIndicator
                  :class="[
                    'col-start-1 row-start-1',
                    'inline-flex items-center justify-center',
                    'w-[1rem]',
                    'opacity-30',
                    'text-current',
                  ]"
                >
                  <div i-solar:alt-arrow-right-outline class="size-4" />
                </ComboboxItemIndicator>

                <div :class="['col-start-2', 'min-w-0', 'flex', 'items-center', 'gap-2', 'py-1']">
                  <slot
                    name="option"
                    v-bind="{ option }"
                  >
                    <span
                      v-if="option.icon"
                      :class="[
                        'size-4 shrink-0',
                        'text-current',
                        option.icon,
                      ]"
                    />

                    <div :class="['min-w-0', 'flex', 'flex-1', 'flex-col']">
                      <span
                        :class="[
                          'line-clamp-1',
                          'overflow-hidden',
                          'text-ellipsis',
                          'whitespace-nowrap',
                        ]"
                      >
                        {{ option.label }}
                      </span>

                      <span
                        v-if="option.description"
                        :class="[
                          'line-clamp-2',
                          'text-xs',
                          'text-[var(--text-muted)]',
                        ]"
                      >
                        {{ option.description }}
                      </span>
                    </div>
                  </slot>
                </div>
              </ComboboxItem>
            </ComboboxGroup>
          </template>
        </ComboboxViewport>
      </ComboboxContent>
    </ComboboxPortal>
  </ComboboxRoot>
</template>
