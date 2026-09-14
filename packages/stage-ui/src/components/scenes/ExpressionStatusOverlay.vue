<script setup lang="ts">
/**
 * ExpressionStatusOverlay — a subtle, non-interactive status pill that surfaces the
 * avatar's live expressiveness state on the 2D stage (reference: AIVTuber's clear
 * state readouts). It visualizes the real-time emotion driven by #20/#102 and the
 *人格 bond derived from the continuous-learning engine, so the user can *see* what
 * the 3D avatar is feeling without switching to the 3D view.
 *
 * Decoupled on purpose: the parent (Stage.vue) maps the rich `performanceState` /
 * `personaState` into the small structural shape below, so this component carries
 * no dependency on memory-pgvector / agent-continuous-learning types.
 */
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  /** Current performance emotion label (e.g. 'happy' | 'neutral'). */
  emotion?: string | null
  /** Current gaze marker, if any (LPM-style look target). */
  gaze?: string | null
  /** Intimacy warmth 0..1 — drives the bond meter + label. */
  warmth?: number | null
  /** Intimacy familiarity 0..1. */
  familiarity?: number | null
  /** Intimacy longing 0..1. */
  longing?: number | null
  /** Live user-audio arousal (LPM "listen audio branch"), 0..1. Drives the listening-liveliness meter. */
  listenArousal?: number | null
  /** Master visibility (only shown while the stage is mounted). */
  visible?: boolean
}>(), {
  emotion: null,
  gaze: null,
  warmth: null,
  familiarity: null,
  longing: null,
  listenArousal: null,
  visible: true,
})

const emotionLabel = computed(() => (props.emotion ?? 'neutral').toString())

const emotionColor = computed(() => {
  switch ((props.emotion ?? '').toLowerCase()) {
    case 'happy':
    case 'joy':
      return '#fbbf24'
    case 'sad':
    case 'sadness':
      return '#60a5fa'
    case 'angry':
    case 'anger':
      return '#f87171'
    case 'surprised':
    case 'surprise':
      return '#a78bfa'
    case 'relaxed':
    case 'calm':
      return '#34d399'
    default:
      return '#94a3b8' // neutral / unknown
  }
})

const warmthPct = computed(() => Math.round(Math.min(1, Math.max(0, props.warmth ?? 0)) * 100))

const bondLabel = computed(() => {
  const w = props.warmth ?? 0
  if (w >= 0.75)
    return '亲密'
  if (w >= 0.5)
    return '熟悉'
  if (w >= 0.25)
    return '试探'
  return '陌生'
})

const listenPct = computed(() => Math.round(Math.min(1, Math.max(0, props.listenArousal ?? 0)) * 100))
</script>

<template>
  <transition name="expr-fade">
    <div
      v-if="visible"
      class="expr-overlay pointer-events-none absolute bottom-3 left-3 z-20 flex select-none items-center gap-2 rounded-full bg-$scrim px-3 py-1.5 text-xs text-$text-primary shadow-sm backdrop-blur-sm"
    >
      <span class="inline-block h-2.5 w-2.5 shrink-0 rounded-full" :style="{ backgroundColor: emotionColor }" />
      <span class="font-medium capitalize">{{ emotionLabel }}</span>
      <span class="opacity-40">·</span>
      <span class="opacity-80">{{ bondLabel }}</span>
      <span class="ml-1 h-1.5 w-12 inline-flex overflow-hidden rounded-full bg-$surface-1">
        <span
          class="h-full rounded-full from-pink-400 to-rose-400 bg-gradient-to-r transition-[width] duration-500"
          :style="{ width: `${warmthPct}%` }"
        />
      </span>
      <span v-if="listenArousal != null" class="ml-1 opacity-60">倾听 {{ listenPct }}%</span>
      <span v-if="listenArousal != null" class="ml-0.5 h-1.5 w-10 inline-flex overflow-hidden rounded-full bg-$surface-1">
        <span
          class="h-full rounded-full from-cyan-400 to-sky-400 bg-gradient-to-r transition-[width] duration-300"
          :style="{ width: `${listenPct}%` }"
        />
      </span>
      <span v-if="gaze" class="ml-0.5 opacity-60">视线 {{ gaze }}</span>
    </div>
  </transition>
</template>

<style scoped>
.expr-overlay {
  font-variant-numeric: tabular-nums;
}
.expr-fade-enter-active,
.expr-fade-leave-active {
  transition: opacity 0.4s ease;
}
.expr-fade-enter-from,
.expr-fade-leave-to {
  opacity: 0;
}
</style>
