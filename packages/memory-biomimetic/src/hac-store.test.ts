import type { Appraisal } from './contracts'
import type { EndogenousState } from './hac'

import { describe, expect, it } from 'vitest'

import { DEFAULT_HAC_CONFIG } from './hac'
import { BioticMemory } from './store'
import { DEFAULT_MEMORY_CONFIG } from './types'

function dim(c: number): EndogenousState {
  return { a: 0.5, v: 0.5, d: 0.5, n: 0.5, s: 0.5, c, b: 0.5 }
}

describe('hac integration in store (§9, opt-in)', () => {
  it('is absent unless enabled, so baseline retrieval stays deterministic', () => {
    const m = new BioticMemory()
    expect(m.hacState()).toBeUndefined()
    m.encode({ id: 'e1', content: 'the server crashed', createdAt: 0, context: { tags: [] } })
    // bump=false so accessCount is not mutated between calls → deterministic
    const a = m.retrieve('server', 10, false)[0]?.score
    const b = m.retrieve('server', 10, false)[0]?.score
    expect(a).toBe(b)
  })

  it('enabled HAC adds cognitive-load-driven degradation that scales with load', () => {
    const low = new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, hac: { ...DEFAULT_HAC_CONFIG, enabled: true } })
    const high = new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, hac: { ...DEFAULT_HAC_CONFIG, enabled: true } })
    for (const m of [low, high]) {
      m.encode({ id: 'e1', content: 'the server crashed at 03:14', createdAt: 0, context: { tags: [] } })
      m.encode({ id: 'e2', content: 'user reported a login bug', createdAt: 0, context: { tags: [] } })
    }
    // drive low store toward zero load, high store toward full load
    for (let i = 0; i < 30; i++) {
      low.stepHac(dim(0), dim(0))
      high.stepHac(dim(1), dim(0))
    }
    const variance = (store: BioticMemory): number => {
      const scores: number[] = []
      for (let i = 0; i < 400; i++) {
        const r = store.retrieve('server crash')
        scores.push(r[0]?.score ?? 0)
      }
      const mean = scores.reduce((s, x) => s + x, 0) / scores.length
      return scores.reduce((s, x) => s + (x - mean) ** 2, 0) / scores.length
    }
    const vLow = variance(low)
    const vHigh = variance(high)
    expect(vLow).toBeGreaterThan(0)
    expect(vHigh).toBeGreaterThan(vLow)
  })
})

describe('hac closed-loop in store (§25 #2/#3)', () => {
  const appraisal = (d: Partial<Appraisal['dimensions']>): Appraisal => ({
    id: 'a1',
    schema: 'aijade.appraisal@1',
    eventRef: 'e1',
    agentId: 'x',
    userScope: 'u',
    dimensions: {
      valence: 0,
      arousal: 1,
      goalRelevance: 0.5,
      novelty: 0.5,
      control: 0,
      urgency: 0.5,
      ...d,
    },
    confidence: 1,
    appraisedBy: 'agent',
    appraisedAt: 0,
  })

  it('stepHacAppraisal drives z_t only when HAC is enabled', () => {
    const m = new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, hac: { ...DEFAULT_HAC_CONFIG, enabled: true } })
    const before = m.hacState()!.a
    m.stepHacAppraisal(appraisal({ arousal: 1 }))
    const after = m.hacState()!.a
    expect(after).toBeGreaterThan(before)
  })

  it('hacSnapshot returns a frozen, source-tagged snapshot only when enabled', () => {
    const off = new BioticMemory()
    expect(off.hacSnapshot()).toBeUndefined()

    const on = new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, hac: { ...DEFAULT_HAC_CONFIG, enabled: true } })
    on.stepHacAppraisal(appraisal({ arousal: 1 }))
    const snap = on.hacSnapshot()
    expect(snap).toBeDefined()
    expect(snap!.frozen).toBe(true)
    expect(snap!.source).toBe('hac')
    expect(snap!.state.arousal).toBeCloseTo(on.hacState()!.a, 12)
  })
})
