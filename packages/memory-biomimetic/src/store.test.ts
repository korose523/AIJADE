import type { MemoryConfig } from './types'

import { describe, expect, it } from 'vitest'

import { BioticMemory } from './store'
import { DEFAULT_GATING, DEFAULT_MEMORY_CONFIG, NO_GATING } from './types'

const HIGH_SALIENCE = 'Caroline went to the LGBTQ support group yesterday with my sister'
const LOW_SALIENCE = 'haha?'

function mkMem(gating: MemoryConfig['gating'], override: Partial<MemoryConfig> = {}): BioticMemory {
  return new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, gating, ...override }, 0)
}

describe('bioticMemory.encode durability', () => {
  it('salient content under DEFAULT > 1, under NO_GATING == 1', () => {
    const on = mkMem(DEFAULT_GATING)
    on.encode({ id: 'e1', content: HIGH_SALIENCE, createdAt: 0, context: { tags: [] } })
    const off = mkMem(NO_GATING)
    off.encode({ id: 'e1', content: HIGH_SALIENCE, createdAt: 0, context: { tags: [] } })
    expect(on.episodes[0].durability).toBeGreaterThan(1)
    expect(off.episodes[0].durability).toBe(1)
  })

  it('durability is driven by content salience, not hormones', () => {
    const m = mkMem(DEFAULT_GATING)
    m.encode({ id: 'hi', content: HIGH_SALIENCE, createdAt: 0, context: { tags: [] } })
    m.encode({ id: 'lo', content: LOW_SALIENCE, createdAt: 0, context: { tags: [] } })
    // high-salience content gets higher durability than low-salience content
    expect(m.episodes[0].durability).toBeGreaterThan(m.episodes[1].durability)
    // encoding carries the predicted content salience (sigmoid of the v2 score)
    expect(m.episodes[0].encoding.salience).toBeGreaterThan(m.episodes[1].encoding.salience)
  })
})

describe('gating does real work at retrieval', () => {
  it('at a long horizon a salient episode scores higher under ON than OFF', async () => {
    const content = HIGH_SALIENCE
    const build = async (gating: MemoryConfig['gating']) => {
      const m = mkMem(gating)
      m.encode({ id: 'salient', content, createdAt: 0, context: { tags: [] } })
      m.encode({ id: 'noise', content: 'the weather was rainy and the dog barked at the mailman on tuesday morning', createdAt: 0, context: { tags: [] } })
      await m.consolidate()
      m.setNow(DEFAULT_MEMORY_CONFIG.forgetting.ageScaleMs * 365)
      const top = m.retrieve(content, 5, false)
      return top.find(c => c.id === 'salient')!
    }
    const onC = await build(DEFAULT_GATING)
    const offC = await build(NO_GATING)
    expect(onC.score).toBeGreaterThan(offC.score)
  })
})

describe('consolidate selects by content salience', () => {
  it('prunes low-salience episodes and keeps high-salience ones', async () => {
    const m = mkMem(DEFAULT_GATING, { consolidateThreshold: 2 })
    m.encode({ id: 'hi', content: HIGH_SALIENCE, createdAt: 0, context: { tags: [] } })
    m.encode({ id: 'lo', content: LOW_SALIENCE, createdAt: 0, context: { tags: [] } })
    const res = await m.consolidate()
    expect(res.facts).toHaveLength(1)
    expect(res.consumed).toEqual(['hi'])
    expect(m.episodes.find(e => e.id === 'lo')!.forgotten).toBe(true)
    expect(m.episodes.find(e => e.id === 'hi')!.forgotten).toBeFalsy()
  })

  it('under NO_GATING everything is distilled (nothing pruned)', async () => {
    const m = mkMem(NO_GATING, { consolidateThreshold: 2 })
    m.encode({ id: 'hi', content: HIGH_SALIENCE, createdAt: 0, context: { tags: [] } })
    m.encode({ id: 'lo', content: LOW_SALIENCE, createdAt: 0, context: { tags: [] } })
    const res = await m.consolidate()
    expect(res.facts).toHaveLength(2)
    expect(m.episodes.find(e => e.id === 'lo')!.forgotten).toBeFalsy()
  })
})

describe('retrieve skips expired / out-of-valid-window entries', () => {
  it('expired episodes are not returned', () => {
    const m = mkMem(DEFAULT_GATING)
    const ep = m.encode({ id: 'keep', content: HIGH_SALIENCE, createdAt: 0, context: { tags: [] } })
    ep.status = 'expired'
    const top = m.retrieve(HIGH_SALIENCE, 10, false)
    expect(top.find(c => c.id === 'keep')).toBeUndefined()
  })

  it('entries outside their validTime window are not returned', () => {
    const m = mkMem(DEFAULT_GATING)
    m.setNow(1000)
    const ep = m.encode({ id: 'keep', content: HIGH_SALIENCE, createdAt: 100, context: { tags: [] } })
    ep.validTime = { validUntil: 500 } // now (1000) is after validUntil (500)
    const top = m.retrieve(HIGH_SALIENCE, 10, false)
    expect(top.find(c => c.id === 'keep')).toBeUndefined()
  })

  it('active entries inside their validTime window are returned', () => {
    const m = mkMem(DEFAULT_GATING)
    m.encode({ id: 'keep', content: HIGH_SALIENCE, createdAt: 0, context: { tags: [] } })
    const top = m.retrieve(HIGH_SALIENCE, 10, false)
    expect(top.find(c => c.id === 'keep')).toBeDefined()
  })
})

describe('retrieve R-conflict penalty', () => {
  it('penalises the older + lower-durability conflicting candidate (loser kept for audit)', () => {
    const m = mkMem(DEFAULT_GATING, { conflictPenalty: 1 })
    // A: no negation, older, lower durability. B: negation ("doesn't"), newer, higher durability.
    m.encode({ id: 'A', content: 'Caroline likes Paris', createdAt: 0, baseStrength: 1, context: { tags: [] } })
    m.encode({ id: 'B', content: 'Caroline doesn\'t like Paris', createdAt: 1000, baseStrength: 2, context: { tags: [] } })

    const q = 'Caroline Paris'
    const noPenalty = m.retrieve(q, 10, false)
    const aNoPenalty = noPenalty.find(c => c.id === 'A')!

    m.config.conflictPenalty = 0.5
    const withPenalty = m.retrieve(q, 10, false)
    const aPen = withPenalty.find(c => c.id === 'A')!
    const bPen = withPenalty.find(c => c.id === 'B')!

    // loser A is flagged; winner B is not
    expect(aPen.parts.conflict).toBe(true)
    expect(bPen.parts.conflict).toBeFalsy()
    // winner scores higher than the penalised loser
    expect(bPen.score).toBeGreaterThan(aPen.score)
    // penalty multiplies the loser by exactly conflictPenalty (0.5)
    expect(aPen.score).toBeCloseTo(aNoPenalty.score * 0.5, 9)
    // both entries remain in the store (audit)
    expect(m.episodes).toHaveLength(2)
  })
})
