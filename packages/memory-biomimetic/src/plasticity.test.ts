import type { PlasticityGate } from './plasticity'
import type { ContentSalience, PhysiologicalState, PhysiologicalStateV3 } from './types'

import { describe, expect, it } from 'vitest'

import {
  applyRetrievalNoise,
  clampGate,
  deriveGate,
  deriveGateFromContent,
  derivePresentationModulation,
  deterministicUnit,
  GATE_BOUNDS,
  GATE_KEYS,
  gateFromCoefficients,
  isNeutralGate,
  NEUTRAL_GATE,
} from './plasticity'
import { DEFAULT_GATING, NEUTRAL_PHYSIOLOGY_V3, NEUTRAL_PRESENTATION, NO_GATING } from './types'

const CALM: PhysiologicalState = {
  dopamine: 0.5,
  serotonin: 0.5,
  cortisol: 0.3,
  oxytocin: 0.5,
  adrenaline: 0.3,
  affect: { valence: 0.5, arousal: 0.5, dominance: 0.5 },
}

function hormones(over: Partial<PhysiologicalState> = {}): PhysiologicalState {
  return { ...CALM, ...over }
}

describe('plasticity gate — v3 §2.3 / v4 §5.4', () => {
  it('the neutral gate is the identity — that IS the ablation control (v3 §7)', () => {
    expect(NEUTRAL_GATE.consolidationGain).toBe(1)
    expect(NEUTRAL_GATE.decayMultiplier).toBe(1)
    expect(NEUTRAL_GATE.retrievalNoise).toBe(0)
    expect(NEUTRAL_GATE.moodCongruenceWeight).toBe(0)
    expect(NEUTRAL_GATE.socialBonus).toBe(1)
    expect(NEUTRAL_GATE.explorationTemperature).toBe(0)
    expect(isNeutralGate(NEUTRAL_GATE)).toBe(true)
  })

  it('no gating maps to the neutral gate for EVERY state — the ablation stays clean', () => {
    const states = [
      hormones(),
      hormones({ cortisol: 1, dopamine: 1, adrenaline: 1 }),
      hormones({ cortisol: 0, dopamine: 0, oxytocin: 0 }),
      hormones({ intimacy: 1 }),
    ]
    for (const s of states) {
      const g = gateFromCoefficients(NO_GATING, s)
      expect(isNeutralGate(g)).toBe(true)
    }
  })

  it('every gate field stays inside the v3 §2.3 bounds', () => {
    for (let i = 0; i < 200; i++) {
      const s = hormones({
        dopamine: i / 199,
        cortisol: 1 - i / 199,
        serotonin: (i * 7 % 200) / 199,
        oxytocin: (i * 13 % 200) / 199,
        adrenaline: (i * 29 % 200) / 199,
        intimacy: (i * 37 % 200) / 199,
      })
      for (const g of [deriveGate(s, i / 199), gateFromCoefficients(DEFAULT_GATING, s)]) {
        for (const k of GATE_KEYS) {
          expect(g[k]).toBeGreaterThanOrEqual(GATE_BOUNDS[k].min)
          expect(g[k]).toBeLessThanOrEqual(GATE_BOUNDS[k].max)
        }
      }
    }
  })

  it('clampGate pulls out-of-range values back into bounds', () => {
    const wild: PlasticityGate = {
      consolidationGain: 99,
      decayMultiplier: -5,
      retrievalNoise: 10,
      moodCongruenceWeight: -1,
      socialBonus: 0,
      explorationTemperature: 1e9,
    }
    const c = clampGate(wild)
    expect(c.consolidationGain).toBe(GATE_BOUNDS.consolidationGain.max)
    expect(c.decayMultiplier).toBe(GATE_BOUNDS.decayMultiplier.min)
    expect(c.retrievalNoise).toBe(GATE_BOUNDS.retrievalNoise.max)
    expect(c.moodCongruenceWeight).toBe(0)
    expect(c.socialBonus).toBe(GATE_BOUNDS.socialBonus.min)
    expect(c.explorationTemperature).toBe(GATE_BOUNDS.explorationTemperature.max)
  })
})

describe('retrieval_noise — gating must be able to hurt (v3 §5)', () => {
  it('higher cortisol means worse retrieval, not just better', () => {
    const calm = deriveGate(hormones({ cortisol: 0.1 }))
    const stressed = deriveGate(hormones({ cortisol: 0.9 }))
    expect(stressed.retrievalNoise).toBeGreaterThan(calm.retrievalNoise)
    expect(stressed.decayMultiplier).toBeGreaterThan(calm.decayMultiplier)
  })

  it('noise is deterministic — same key, same degradation (reproducibility)', () => {
    const a = applyRetrievalNoise(1, 'trace-42', 0.3)
    const b = applyRetrievalNoise(1, 'trace-42', 0.3)
    expect(a).toBe(b)
    expect(deterministicUnit('trace-42')).toBe(deterministicUnit('trace-42'))
  })

  it('noise degrades by at most the bound and never to zero or below', () => {
    for (const key of ['a', 'b', 'zzz', 'trace-1', 'trace-2']) {
      const out = applyRetrievalNoise(1, key, 0.3)
      expect(out).toBeLessThanOrEqual(1)
      expect(out).toBeGreaterThan(0.7 - 1e-9)
    }
  })

  it('zero noise is a no-op, so the neutral gate cannot change retrieval', () => {
    expect(applyRetrievalNoise(0.87, 'x', NEUTRAL_GATE.retrievalNoise)).toBe(0.87)
  })

  it('deterministicUnit stays in [0,1)', () => {
    for (let i = 0; i < 500; i++) {
      const u = deterministicUnit(`k${i}`)
      expect(u).toBeGreaterThanOrEqual(0)
      expect(u).toBeLessThan(1)
    }
  })
})

describe('content-salience gate — v2 / P2 (memory is gated by CONTENT, not hormones)', () => {
  const NEUTRAL_CONTENT: ContentSalience = { salience: 0, socialSalience: 0, novelty: 0 }
  const RICH: ContentSalience = { salience: 0.9, socialSalience: 0.7, novelty: 0.6 }

  it('neutral content maps exactly to the neutral gate (the ablation control)', () => {
    const g = deriveGateFromContent(NEUTRAL_CONTENT)
    expect(isNeutralGate(g)).toBe(true)
    expect(g).toEqual(NEUTRAL_GATE)
  })

  it('rich content raises consolidation gain + social bonus, lowers decay multiplier', () => {
    const g = deriveGateFromContent(RICH)
    expect(g.consolidationGain).toBeGreaterThan(1)
    expect(g.socialBonus).toBeGreaterThan(1)
    expect(g.decayMultiplier).toBeLessThan(1)
    // within bounds
    for (const k of GATE_KEYS) {
      expect(g[k]).toBeGreaterThanOrEqual(GATE_BOUNDS[k].min)
      expect(g[k]).toBeLessThanOrEqual(GATE_BOUNDS[k].max)
    }
  })

  it('gateFromCoefficients(NO_GATING) stays neutral for every state (ablation stays clean)', () => {
    const states: PhysiologicalState[] = [
      hormones(),
      hormones({ cortisol: 1, dopamine: 1, adrenaline: 1 }),
      hormones({ cortisol: 0, dopamine: 0, oxytocin: 0 }),
      hormones({ intimacy: 1 }),
    ]
    for (const s of states) {
      expect(isNeutralGate(gateFromCoefficients(NO_GATING, s))).toBe(true)
    }
  })
})

describe('presentation modulation — disable-able L3 expression layer', () => {
  it('returns NEUTRAL presentation when disabled, regardless of state', () => {
    const excited: PhysiologicalStateV3 = {
      trait: { dopamine: 1, serotonin: 1, cortisol: 0, oxytocin: 1, adrenaline: 1 },
      mood: { dopamine: 1, serotonin: 1, cortisol: 0, oxytocin: 1, adrenaline: 1 },
      transient: { dopamine: 1, serotonin: 1, cortisol: 0, oxytocin: 1, adrenaline: 1 },
      affect: { valence: 1, arousal: 1, dominance: 1 },
      intimacy: 1,
    }
    expect(derivePresentationModulation(excited, false)).toEqual(NEUTRAL_PRESENTATION)
    expect(derivePresentationModulation(NEUTRAL_PHYSIOLOGY_V3, false)).toEqual(NEUTRAL_PRESENTATION)
  })

  it('enabled neutral state yields a near-neutral modulation (no expressive bias)', () => {
    const m = derivePresentationModulation(NEUTRAL_PHYSIOLOGY_V3, true)
    expect(m.warmth).toBeCloseTo(0.5)
    expect(m.verbosity).toBeCloseTo(0.5)
    expect(m.hesitation).toBeCloseTo(0)
    expect(m.energy).toBeCloseTo(0.5)
  })

  it('enabled high-cortisol state raises hesitation (a real expressive effect, not a memory effect)', () => {
    const stressed: PhysiologicalStateV3 = {
      trait: { dopamine: 0.5, serotonin: 0.5, cortisol: 1, oxytocin: 0.5, adrenaline: 0.5 },
      mood: { dopamine: 0.5, serotonin: 0.5, cortisol: 1, oxytocin: 0.5, adrenaline: 0.5 },
      transient: { dopamine: 0.5, serotonin: 0.5, cortisol: 1, oxytocin: 0.5, adrenaline: 0.5 },
      affect: { valence: 0.5, arousal: 0.5, dominance: 0.5 },
    }
    expect(derivePresentationModulation(stressed, true).hesitation).toBeGreaterThan(0)
  })
})
