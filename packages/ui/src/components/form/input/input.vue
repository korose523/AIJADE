<script
  setup
  lang="ts"
  generic="InputType extends 'number' | InputTypeHTMLAttribute | string, T = InputType extends 'number' ? (number | undefined) : ((string | undefined))"
>
import type { InputTypeHTMLAttribute } from 'vue'

// Define button variants for better type safety and maintainability
type InputVariant = 'primary' | 'secondary' | 'primary-dimmed'

type InputTheme = 'default'

// Define size options for better flexibility
type InputSize = 'sm' | 'md' | 'lg'

const props = withDefaults(defineProps<{
  type?: InputType
  variant?: InputVariant // Button style variant
  size?: InputSize // Button size variant
  theme?: InputTheme // Button theme
  /**
   * Forwarded to the underlying `<input>` element so the browser participates
   * in form validation (HTML5 `:invalid` styling and submit blocking) without
   * the consumer having to drop down to raw HTML.
   */
  required?: boolean
}>(), {
  variant: 'primary',
  size: 'md',
  theme: 'default',
})

const modelValue = defineModel<T>({ required: false })

const variantClasses: Record<InputVariant, Record<InputTheme, {
  default: string[]
}>> = {
  'primary': {
    default: {
      default: [
        'w-full rounded-lg px-2 py-1 text-nowrap text-sm outline-none',
        'bg-$surface-1 bg-$surface-1 focus:bg-$surface-1 focus:bg-$surface-1',
        'focus:border-primary-300 focus:border-primary-400/50 border-2 border-solid border-$hairline border-$hairline',
        'text-disabled:$text-muted text-disabled:$text-secondary',
        'shadow-sm',
      ],
    },
  },
  'secondary': {
    default: {
      default: [
        'w-full rounded-lg px-2 py-1 text-nowrap text-sm outline-none',
        'bg-$surface-1 bg-$surface-1 focus:bg-$surface-1 focus:bg-$surface-1',
        'focus:border-primary-300 focus:border-primary-400/50 border-2 border-solid border-$hairline border-$hairline',
        'text-disabled:$text-muted text-disabled:$text-secondary',
        'shadow-sm',
      ],
    },
  },
  'primary-dimmed': {
    default: {
      default: [
        'w-full rounded-lg px-2 py-1 text-nowrap text-sm outline-none',
        'bg-$surface-1 bg-$surface-2 focus:bg-$surface-1 focus:bg-$surface-1',
        'focus:border-primary-500/30 focus:border-primary-400/50 border-2 border-solid border-$hairline border-$hairline',
        'text-disabled:$text-muted text-disabled:$text-secondary',
      ],
    },
  },
}
</script>

<template>
  <template v-if="props.type === 'number'">
    <input
      v-model.number="modelValue"
      :type="props.type || 'text'"
      :required="props.required"
      :class="[
        'transition-all duration-200 ease-in-out',
        'cursor-disabled:not-allowed',
        ...variantClasses[props.variant][props.theme].default,
      ]"
    >
  </template>
  <template v-else>
    <input
      v-model="modelValue"
      :type="props.type || 'text'"
      :required="props.required"
      :class="[
        'transition-all duration-200 ease-in-out',
        'cursor-disabled:not-allowed',
        ...variantClasses[props.variant][props.theme].default,
      ]"
    >
  </template>
</template>
