<script setup lang="ts">
type ThemeVariant = 'primary' | 'violet' | 'lime' | 'orange'

const props = withDefaults(defineProps<{
  theme?: ThemeVariant
  label?: string
}>(), {
  theme: 'primary',
})

const themeClasses: Record<ThemeVariant, {
  container: string[]
  label?: string[]
}> = {
  primary: {
    container: [
      'text-[var(--text-primary)]',
      'bg-[var(--surface-2)] border border-[var(--hairline)] backdrop-blur-md',
      `before:bg-[var(--accent)] before:content-[''] before:bg-[var(--accent)]`,
    ],
    label: [
      'text-[var(--accent-strong)] font-semibold',
    ],
  },
  lime: {
    container: [
      'text-[var(--text-primary)]',
      'bg-[var(--surface-2)] border border-[var(--hairline)] backdrop-blur-md',
      `before:bg-[var(--accent)] before:content-[''] before:bg-[var(--accent)]`,
    ],
    label: [
      'text-[var(--accent-strong)] font-semibold',
    ],
  },
  violet: {
    container: [
      'text-[var(--text-primary)]',
      'bg-[var(--surface-2)] border border-[var(--hairline)] backdrop-blur-md',
      `before:bg-[var(--accent)] before:content-[''] before:bg-[var(--accent)]`,
    ],
    label: [
      'text-[var(--accent-strong)] font-semibold',
    ],
  },
  orange: {
    container: [
      'text-[var(--text-primary)]',
      'bg-[var(--surface-2)] border border-[var(--hairline)] backdrop-blur-md',
      `before:bg-[var(--accent)] before:content-[''] before:bg-[var(--accent)]`,
    ],
    label: [
      'text-[var(--accent-strong)] font-semibold',
    ],
  },
}
</script>

<template>
  <div
    relative
    flex flex-col gap-1
    rounded-lg
    py="2.5" pl="5" pr-3
    :class="[
      ...themeClasses[props.theme || 'violet'].container,
      // eslint-disable-next-line vue/prefer-separate-static-class
      'before-position-absolute before:left-2 before:right-0 before:h-[calc(100%-1rem)] before:top-50% before:translate-y--50% before:w-1 before:rounded-full',
    ]"
  >
    <div text="font-semibold" :class="[...(themeClasses[props.theme || 'violet'].label || [])]">
      <slot name="label">
        {{ props.label || 'Callout' }}
      </slot>
    </div>
    <slot />
  </div>
</template>
