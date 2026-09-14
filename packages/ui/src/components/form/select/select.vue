<script setup lang="ts" generic="T extends AcceptableValue">
import type { AcceptableValue } from 'reka-ui'

import {
  SelectArrow,
  SelectContent,
  SelectGroup,
  SelectIcon,
  SelectLabel,
  SelectPortal,
  SelectRoot,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
  SelectViewport,
} from 'reka-ui'
import { computed } from 'vue'

import SelectOption from './select-option.vue'

interface SelectOptionItem<T extends AcceptableValue> {
  label: string
  value: T
  description?: string
  disabled?: boolean
  icon?: string
}

interface SelectOptionGroupItem<T extends AcceptableValue> {
  groupLabel?: string
  children?: SelectOptionItem<T>[]
}

const props = withDefaults(defineProps<{
  options: SelectOptionItem<T>[] | SelectOptionGroupItem<T>[]
  placeholder?: string
  disabled?: boolean
  by?: string | ((a: T, b: T) => boolean)
  contentMinWidth?: string | number
  contentWidth?: string | number
  shape?: 'rounded' | 'default'
  variant?: 'blurry' | 'default'
  class?: string | string[]
}>(), {
  placeholder: 'Select an option',
  disabled: false,
  by: undefined,
  contentMinWidth: 160,
  contentWidth: undefined,
  shape: 'default',
  variant: 'default',
})

const modelValue = defineModel<T>({ required: false })

const normalizedOptions = computed<SelectOptionGroupItem<T>[]>(() => {
  if (!props.options.length) {
    return []
  }

  const [firstOption] = props.options
  if ('value' in firstOption) {
    return [
      {
        groupLabel: '',
        children: props.options as SelectOptionItem<T>[],
      },
    ]
  }

  return props.options as SelectOptionGroupItem<T>[]
})

const flattenedOptions = computed<SelectOptionItem<T>[]>(() =>
  normalizedOptions.value.flatMap(group => group.children ?? []),
)

const selectedOption = computed<SelectOptionItem<T> | undefined>(() =>
  flattenedOptions.value.find(option => isSelectedOption(option.value, modelValue.value)),
)

function isSelectedOption(a: T, b: T | undefined): boolean {
  if (b == null) {
    return false
  }

  if (typeof props.by === 'function') {
    return props.by(a, b)
  }

  if (typeof props.by === 'string') {
    return (a as Record<string, unknown> | null)?.[props.by] === (b as Record<string, unknown> | null)?.[props.by]
  }

  return a === b
}

function toCssSize(value?: string | number): string | undefined {
  if (value == null) {
    return undefined
  }

  return typeof value === 'number' ? `${value}px` : value
}
</script>

<template>
  <SelectRoot
    v-model="modelValue"
    :by="props.by"
    :disabled="props.disabled"
  >
    <SelectTrigger
      :class="[
        'group',
        ...Array.isArray(props.class) ? props.class : [props.class],
        'w-full inline-flex items-center justify-between border px-3 leading-none h-9 gap-[5px] outline-none',
        props.shape === 'rounded' ? 'rounded-full' : 'rounded-lg',
        'text-sm text-$text-primary text-$text-primary data-[placeholder]:text-$text-muted data-[placeholder]:text-$text-secondary',
        props.variant === 'default' ? 'bg-$surface-1 bg-$surface-1 disabled:bg-$surface-1 hover:bg-$surface-1 disabled:bg-$surface-1 hover:bg-$surface-3' : '',
        props.variant === 'blurry' ? 'bg-$surface-1 bg-$surface-2 disabled:bg-$surface-1 hover:bg-$surface-1 disabled:bg-$surface-1 hover:bg-$surface-2' : '',
        props.variant === 'blurry' ? 'backdrop-blur-md' : '',
        'border-2 border-solid focus:border-primary-300 focus:border-primary-400/50',
        props.variant === 'default' ? 'border-$hairline border-$hairline' : '',
        props.variant === 'blurry' ? 'border-$hairline border-$hairline' : '',
        'shadow-sm focus:shadow-[0_0_0_2px] focus:shadow-black/10 focus:shadow-black/30',
        'transition-colors duration-200 ease-in-out',
        props.disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer',
      ]"
    >
      <div :class="['min-w-0 flex-1 text-left']">
        <slot
          v-if="$slots.value"
          name="value"
          v-bind="{ option: selectedOption, value: modelValue, placeholder: props.placeholder }"
        >
          <span
            :class="[
              'block truncate',
              selectedOption ? 'text-$text-primary text-$text-primary' : 'text-$text-muted text-$text-secondary',
            ]"
          >
            {{ selectedOption?.label ?? props.placeholder }}
          </span>
        </slot>
        <SelectValue
          v-else
          v-model="modelValue"
        />
      </div>
      <SelectIcon as-child>
        <div
          i-solar:alt-arrow-down-linear
          :class="[
            'h-4 w-4 shrink-0',
            'text-$text-primary text-$text-primary',
            'transition-transform duration-200 ease-in-out',
            'group-data-[state=open]:rotate-180',
          ]"
        />
      </SelectIcon>
    </SelectTrigger>

    <SelectPortal>
      <SelectContent
        position="popper"
        side="bottom"
        align="start"
        :side-offset="4"
        :avoid-collisions="true"
        :class="[
          // NOTICE: DialogContent/DialogOverlay use z-[9999], and DrawerContent uses z-[1000].
          // SelectContent must render above these layers so that dropdowns inside
          // Dialog/Drawer are not hidden behind the overlay or dismissed unexpectedly.
          // Read more at: https://github.com/moeru-ai/airi/issues/1136
          'z-[10010]',
          'overflow-hidden rounded-xl shadow-sm border will-change-[opacity,transform]',
          'data-[side=top]:animate-slideDownAndFade data-[side=right]:animate-slideLeftAndFade data-[side=bottom]:animate-slideUpAndFade data-[side=left]:animate-slideRightAndFade',
          'bg-$surface-1 bg-$surface-1',
          'border-$hairline border-$hairline border-solid border-2',
        ]"
        :style="{
          width: toCssSize(props.contentWidth) ?? 'var(--reka-select-trigger-width)',
          minWidth: toCssSize(props.contentMinWidth),
        }"
      >
        <SelectViewport
          :class="[
            'p-[2px]',
            'max-h-50dvh',
            'overflow-y-auto',
          ]"
        >
          <template
            v-for="(group, groupIndex) in normalizedOptions"
            :key="group.groupLabel || `group-${groupIndex}`"
          >
            <SelectGroup :class="['overflow-x-hidden']">
              <SelectSeparator
                v-if="groupIndex !== 0"
                :class="['m-[5px]', 'h-[1px]', 'bg-$surface-1 bg-$surface-2']"
              />

              <SelectLabel
                v-if="group.groupLabel"
                :class="[
                  'px-[25px] text-xs leading-[25px]',
                  'text-$text-secondary text-$text-muted',
                  'transition-colors duration-200 ease-in-out',
                ]"
              >
                {{ group.groupLabel }}
              </SelectLabel>

              <SelectOption
                v-for="(option, optionIndex) in group.children || []"
                :key="`${group.groupLabel || groupIndex}-${option.label}-${optionIndex}`"
                :option="option"
              >
                <template
                  v-if="$slots.option"
                  #default="{ option: slotOption }"
                >
                  <slot
                    name="option"
                    v-bind="{ option: slotOption }"
                  />
                </template>
              </SelectOption>
            </SelectGroup>
          </template>
        </SelectViewport>

        <SelectArrow
          :class="[
            'fill-white fill-$text-primary',
            'stroke-$hairline-strong stroke-$hairline-strong',
          ]"
        />
      </SelectContent>
    </SelectPortal>
  </SelectRoot>
</template>
