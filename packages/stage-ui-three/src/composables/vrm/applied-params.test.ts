import type { PerformanceState } from '@proj-aijade/memory-pgvector/performance'

import type { PersonaSignal } from '../../libs/emotion/avatar-expression'

import { describe, expect, it, vi } from 'vitest'

import { useAvatarAnimation } from './use-avatar-animation'

/**
 * `applyPerformance` must report ONLY what was *actually written* to the render
 * model this frame — not the "intent". Several write sites short-circuit
 * (`emotion === lastEmotion`, `engaged !== lastEngaged`, `state.gaze !== lastGaze`),
 * and a `null` gaze means "clear direction" (no write). These tests pin that
 * contract end-to-end through the public `applyPerformance` return value.
 *
 * All cases drive the `speak` branch so the autonomous `idleCtrl.tick` (which can
 * fire spontaneous micro-gestures) never runs — keeping the map deterministic.
 */

function makeEmote() {
  return {
    setEmotion: vi.fn(),
    setEmotionWithResetAfter: vi.fn(),
  }
}

function makeBlink() {
  return {
    setEngaged: vi.fn(),
    setRateScale: vi.fn(),
  }
}

function speakState(emotion: string, extra: Partial<PerformanceState> = {}): PerformanceState {
  return {
    state: 'speak',
    emotion: emotion as PerformanceState['emotion'],
    relationDelta: 0,
    listenArousal: 0,
    ...extra,
  }
}

function listenState(emotion: string, extra: Partial<PerformanceState> = {}): PerformanceState {
  return {
    state: 'listen',
    emotion: emotion as PerformanceState['emotion'],
    relationDelta: 0,
    listenArousal: 0,
    ...extra,
  }
}

// Minimal valid persona so the autonomous-idle branch (`if (currentPersona)`) runs
// and exercises `blink.setRateScale` / `blink.setEngaged` guards end-to-end.
const persona: PersonaSignal = {
  intimacy: { warmth: 0.5, trust: 0.5, familiarity: 0.5, longing: 0.5 },
  endocrine: { dopamine: 0.5, serotonin: 0.5, cortisol: 0.5, oxytocin: 0.5, adrenaline: 0.5 },
  vector: { playfulness: 0.5, spontaneity: 0.5 },
}

describe('useAvatarAnimation.applyPerformance — applied params reporting', () => {
  it('(a) same state applied twice → second map is empty (no false "wrote" on short-circuit)', () => {
    const emote = makeEmote()
    const blink = makeBlink()
    const onGaze = vi.fn()
    const onAppliedParams = vi.fn()
    const { applyPerformance } = useAvatarAnimation(null, null, [], emote, [], blink, onGaze, undefined, undefined, onAppliedParams)

    const first = applyPerformance(speakState('neutral'))
    // First apply legitimately writes emotion + blink.engaged (both were uninitialized).
    expect(first).not.toEqual({})

    const second = applyPerformance(speakState('neutral'))
    // Every write site short-circuits on the identical state → nothing was actually written.
    expect(second).toEqual({})
    expect(onAppliedParams).toHaveBeenLastCalledWith({})
  })

  it('(b) emotion change → map carries emotion.preset + emotion.intensity', () => {
    const emote = makeEmote()
    const blink = makeBlink()
    const { applyPerformance } = useAvatarAnimation(null, null, [], emote, [], blink, undefined)

    const map = applyPerformance(speakState('happy'))
    expect(map['emotion.preset']).toBe('happy')
    expect(typeof map['emotion.intensity']).toBe('number')

    // A subsequent different emotion writes the new preset (not the old one).
    const map2 = applyPerformance(speakState('angry'))
    expect(map2['emotion.preset']).toBe('angry')
  })

  it('(c) emote === undefined → no emotion keys (no write means no record)', () => {
    const blink = makeBlink()
    const { applyPerformance } = useAvatarAnimation(null, null, [], undefined, [], blink, undefined)

    const map = applyPerformance(speakState('happy'))
    expect('emotion.preset' in map).toBe(false)
    expect('emotion.intensity' in map).toBe(false)
    // blink still writes (it is independent of emote).
    expect(map['blink.engaged']).toBe(true)
  })

  it('(d) gesture name is recorded faithfully', () => {
    const emote = makeEmote()
    const blink = makeBlink()
    const { applyPerformance } = useAvatarAnimation(null, null, [], emote, [], blink, undefined)

    const map = applyPerformance(speakState('neutral', { gesture: 'wave' }))
    expect(map.gesture).toBe('wave')
  })

  it('(e) onAppliedParams receives the same map applyPerformance returns', () => {
    const emote = makeEmote()
    const blink = makeBlink()
    const onAppliedParams = vi.fn()
    const { applyPerformance } = useAvatarAnimation(null, null, [], emote, [], blink, undefined, undefined, undefined, onAppliedParams)

    const map = applyPerformance(speakState('happy', { gesture: 'nod' }))
    expect(onAppliedParams).toHaveBeenCalledTimes(1)
    expect(onAppliedParams).toHaveBeenCalledWith(map)
    expect(map['emotion.preset']).toBe('happy')
    expect(map.gesture).toBe('nod')
  })

  it('(f) blink === undefined → no blink.engaged and no blink.rateScale', () => {
    const emote = makeEmote()
    // No blink at all: neither write site may record (call ⟺ record).
    const { applyPerformance } = useAvatarAnimation(null, null, [], emote, [], undefined, undefined)
    const map = applyPerformance(speakState('neutral'))
    expect('blink.engaged' in map).toBe(false)
    expect('blink.rateScale' in map).toBe(false)
  })

  it('(f2) blink === undefined with persona → rateScale guard still covers the optional method', () => {
    const emote = makeEmote()
    // Persona branch would call `blink.setRateScale`, but blink is absent → must not record.
    const { applyPerformance } = useAvatarAnimation(null, null, [], emote, [], undefined, undefined, persona)
    const map = applyPerformance(listenState('neutral'))
    expect('blink.rateScale' in map).toBe(false)
    expect('blink.engaged' in map).toBe(false)
  })

  it('(g) blink has setEngaged but no setRateScale (persona branch) → blink.engaged present, blink.rateScale absent', () => {
    const emote = makeEmote()
    // setRateScale is intentionally missing — the rateScale guard must suppress the write.
    const blink = { setEngaged: vi.fn() }
    const { applyPerformance } = useAvatarAnimation(null, null, [], emote, [], blink, undefined, persona)
    const map = applyPerformance(listenState('neutral'))
    // engaged fires (lastEngaged was null) and IS recorded.
    expect(map['blink.engaged']).toBe(false)
    // rateScale was never called (method absent) → not recorded (no false "wrote").
    expect('blink.rateScale' in map).toBe(false)
  })
})
