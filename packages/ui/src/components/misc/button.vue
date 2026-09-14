<script setup lang="ts">
import { computed } from 'vue'

import { TransitionBidirectional } from '../animations'

// Define button variants for better type safety and maintainability
type ButtonVariant = 'primary' | 'secondary' | 'secondary-muted' | 'danger' | 'caution' | 'pure' | 'ghost'

type ButtonTheme = 'default'

// Define size options for better flexibility
type ButtonSize = 'sm' | 'md' | 'lg'

interface ButtonProps {
  toggled?: boolean // Optional toggled state for toggle buttons
  icon?: string // Icon class name
  label?: string // Button text label
  disabled?: boolean // Disabled state
  loading?: boolean // Loading state
  variant?: ButtonVariant // Button style variant
  size?: ButtonSize // Button size variant
  shape?: 'rounded' | 'pill' | 'square' // Button shape
  theme?: ButtonTheme // Button theme
  block?: boolean // Full width button
}

const props = withDefaults(defineProps<ButtonProps>(), {
  toggled: false,
  variant: 'primary',
  disabled: false,
  loading: false,
  size: 'md',
  shape: 'pill',
  theme: 'default',
  block: false,
})

const isDisabled = computed(() => props.disabled || props.loading)

// Extract variant styles for better organization
const variantClasses: Record<ButtonVariant, Record<ButtonTheme, {
  default: string[]
  nonToggled?: string
  toggled?: string
}>> = {
  'primary': {
    default: {
      default: [
        'rounded-lg',
        'bg-[var(--accent)] hover:bg-[var(--accent-strong)] active:bg-[var(--accent-strong)]',
        'border border-solid border-[var(--hairline)]',
        'text-$text-primary text-neutral-950',
        'focus:ring-[var(--accent)]',
      ],
    },
  },
  'secondary': {
    default: {
      default: [
        'rounded-lg',
        'bg-[var(--surface-2)] hover:bg-[var(--surface-3)] active:bg-[var(--surface-3)]',
        'border border-solid border-[var(--hairline)]',
        'text-[var(--text-primary)]',
        'focus:ring-[var(--hairline-strong)]',
      ],
    },
  },
  'secondary-muted': {
    default: {
      default: [
        'rounded-lg',
        'border border-solid border-[var(--hairline)]',
        'focus:ring-none',
      ],
      nonToggled: 'bg-[var(--surface-2)] text-[var(--text-secondary)]',
      toggled: 'bg-[var(--accent-soft)] ring-2 ring-[var(--accent)] text-[var(--accent-strong)]',
    },
  },
  'danger': {
    default: {
      default: [
        'rounded-lg',
        'backdrop-blur-md',
        'bg-red-500/15 hover:bg-red-500/20 active:bg-red-500/30 bg-red-700/30 hover:bg-red-700/40 active:bg-red-700/30',
        'focus:ring-none',
        'border-2 border-solid border-red-200/30 border-red-900/30',
        'text-red-950 text-red-100',
      ],
    },
  },
  'caution': {
    default: {
      default: [
        'rounded-lg',
        'backdrop-blur-md',
        'bg-amber-400/20 hover:bg-amber-400/25 active:bg-amber-400/35 bg-amber-500/20 hover:bg-amber-500/30 active:bg-amber-500/20',
        'focus:ring-none',
        'border-2 border-solid border-amber-300/30 border-amber-500/15',
        'text-amber-900 text-amber-50',
      ],
    },
  },
  'pure': {
    default: {
      default: [
        'rounded-lg',
        'bg-transparent',
        'text-[var(--text-primary)]',
        '!px-0 !py-0',
      ],
    },
  },
  'ghost': {
    default: {
      default: [
        'rounded-lg',
        'bg-transparent',
        'hover:bg-[var(--surface-2)]',
        'text-[var(--text-secondary)]',
        'focus:ring-none',
      ],
    },
  },
}

// Extract size styles for better organization
const sizeClasses: Record<ButtonSize, string> = {
  sm: props.shape === 'pill'
    ? 'px-3 py-1.5 text-xs'
    : props.shape === 'square'
      ? 'p-2 text-xs'
      : 'px-4 py-2 text-sm',
  md: props.shape === 'pill'
    ? 'px-4 py-2 text-sm'
    : props.shape === 'square'
      ? 'p-3 text-sm'
      : 'px-5 py-3 text-base',
  lg: props.shape === 'pill'
    ? 'px-6 py-3 text-base'
    : props.shape === 'square'
      ? 'p-4 text-base'
      : 'px-6 py-3 text-base',
}

// Base classes that are always applied
const baseClasses = computed(() => {
  const variant = variantClasses[props.variant] || variantClasses.primary
  const theme = variant[props.theme] || variant.default

  return [
    'font-medium outline-none',
    'transition-all duration-200 ease-in-out',
    'disabled:cursor-not-allowed disabled:opacity-50',
    'backdrop-blur-md',
    props.block ? 'w-full' : '',
    sizeClasses[props.size],
    theme.default,
    props.toggled ? theme.toggled || '' : theme.nonToggled || '',
    { 'opacity-50 cursor-not-allowed': isDisabled.value },
    'focus:ring-2',
  ]
})
</script>

<template>
  <button
    :disabled="isDisabled"
    :class="baseClasses"
  >
    <div class="flex flex-row items-center justify-center gap-2">
      <TransitionBidirectional
        from-class="opacity-0 mr-0! w-0!"
        active-class="transition-[width,margin] ease-in-out overflow-hidden transition-100"
      >
        <div v-if="loading || icon" class="w-4">
          <div v-if="loading" class="i-svg-spinners:ring-resize h-4 w-4" />
          <div v-else-if="icon" class="h-4 w-4" :class="icon" />
        </div>
      </TransitionBidirectional>
      <span v-if="label">{{ label }}</span>
      <slot v-else />
    </div>
  </button>
</template>
