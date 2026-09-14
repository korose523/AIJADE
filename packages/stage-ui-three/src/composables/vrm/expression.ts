import type { VRMCore } from '@pixiv/three-vrm-core'

import { ref } from 'vue'

import { smoothTowards } from '../../libs/emotion/avatar-expression'

interface EmotionState {
  expression?: {
    name: string
    value: number
    duration?: number
    curve?: (t: number) => number
  }[]
  blendDuration?: number
}

export function useVRMEmote(vrm: VRMCore) {
  const currentEmotion = ref<string | null>(null)
  const isTransitioning = ref(false)
  const transitionProgress = ref(0)
  const currentExpressionValues = ref(new Map<string, number>())
  const targetExpressionValues = ref(new Map<string, number>())
  const resetTimeout = ref<number>()

  // Utility functions
  const clampIntensity = (value: number): number => {
    return Math.min(1, Math.max(0, value))
  }

  // Emotion states definition — values are the "full weight" targets;
  // actual applied weight is value × clamped intensity.
  // Using slightly lower values (0.7–0.8) for primary expressions to
  // prevent the "too raw / smiles too much" problem reported in #590.
  const emotionStates = new Map<string, EmotionState>([
    ['happy', {
      expression: [
        { name: 'happy', value: 0.7, duration: 0.3 },
        { name: 'aa', value: 0.2 },
      ],
      blendDuration: 0.4,
    }],
    ['sad', {
      expression: [
        { name: 'sad', value: 0.7 },
        { name: 'oh', value: 0.15 },
      ],
      blendDuration: 0.4,
    }],
    ['angry', {
      expression: [
        { name: 'angry', value: 0.7 },
        { name: 'ee', value: 0.3 },
      ],
      blendDuration: 0.3,
    }],
    ['surprised', {
      expression: [
        { name: 'surprised', value: 0.8 },
        { name: 'oh', value: 0.4 },
      ],
      blendDuration: 0.15,
    }],
    ['neutral', {
      expression: [
        { name: 'neutral', value: 1.0 },
      ],
      blendDuration: 0.6,
    }],
    ['think', {
      expression: [
        { name: 'think', value: 0.7 },
      ],
      blendDuration: 0.5,
    }],
  ])

  const clearResetTimeout = () => {
    if (resetTimeout.value) {
      clearTimeout(resetTimeout.value)
      resetTimeout.value = undefined
    }
  }

  const setEmotion = (emotionName: string, intensity = 1) => {
    clearResetTimeout()

    if (!emotionStates.has(emotionName)) {
      console.warn(`Emotion ${emotionName} not found`)
      return
    }

    const emotionState = emotionStates.get(emotionName)!
    currentEmotion.value = emotionName

    const normalizedIntensity = clampIntensity(intensity)

    // Build the new TARGET weights from the live expression map, EXCLUDING
    // `blink` (owned by useBlink) so the two layers never fight over it.
    // Every non-blink expression defaults to 0; the active emotion's
    // expressions override it, scaled by intensity. We do NOT reset
    // currentExpressionValues — `update` smooths current→target every frame,
    // so re-calling setEmotion mid-flight (e.g. streaming tokens flipping
    // happy↔neutral) just redirects smoothly instead of snapping (kills jitter,
    // and fixes the #590 "snaps to 0 first" regression).
    if (vrm.expressionManager) {
      const expressionNames = Object.keys(vrm.expressionManager.expressionMap)
      for (const name of expressionNames) {
        if (name === 'blink')
          continue
        targetExpressionValues.value.set(name, 0)
        if (!currentExpressionValues.value.has(name))
          currentExpressionValues.value.set(name, vrm.expressionManager.getValue(name) || 0)
      }
    }

    for (const expr of emotionState.expression || []) {
      targetExpressionValues.value.set(expr.name, expr.value * normalizedIntensity)
    }
  }

  const setEmotionWithResetAfter = (emotionName: string, ms: number, intensity = 1) => {
    clearResetTimeout()
    setEmotion(emotionName, intensity)

    // Set timeout to reset to neutral
    resetTimeout.value = setTimeout(() => {
      setEmotion('neutral')
      resetTimeout.value = undefined
    }, ms) as unknown as number
  }

  const update = (deltaTime: number) => {
    if (!vrm.expressionManager)
      return

    // Frame-rate-independent exponential smoothing: each frame we move a small
    // step from the currently displayed weight toward the target. Re-targeting
    // an emotion only changes `targetExpressionValues`, so the visible motion
    // always eases — never jumps. ~95% of the gap closes in 3·tau.
    const tau = 0.13
    let maxDist = 0
    for (const [exprName, targetValue] of targetExpressionValues.value) {
      const startValue = currentExpressionValues.value.get(exprName)
        ?? vrm.expressionManager.getValue(exprName)
        ?? 0
      const smoothed = smoothTowards(startValue, targetValue, deltaTime, tau)
      currentExpressionValues.value.set(exprName, smoothed)
      vrm.expressionManager.setValue(exprName, smoothed)
      const d = Math.abs(smoothed - targetValue)
      if (d > maxDist)
        maxDist = d
    }
    isTransitioning.value = maxDist > 0.01
    transitionProgress.value = isTransitioning.value ? Math.max(0, 1 - maxDist) : 1
  }

  const addEmotionState = (emotionName: string, state: EmotionState) => {
    emotionStates.set(emotionName, state)
  }

  const removeEmotionState = (emotionName: string) => {
    emotionStates.delete(emotionName)
  }

  // Cleanup function
  const dispose = () => {
    clearResetTimeout()
  }

  return {
    currentEmotion,
    isTransitioning,
    setEmotion,
    setEmotionWithResetAfter,
    update,
    addEmotionState,
    removeEmotionState,
    dispose,
  }
}
