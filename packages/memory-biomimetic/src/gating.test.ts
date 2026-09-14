import type { ContentSalience } from './types'

import { describe, expect, it } from 'vitest'

import { decayExponent, durability, retrievalBreadth } from './gating'
import { DEFAULT_GATING, NO_GATING } from './types'

const salient: ContentSalience = { salience: 0.9, socialSalience: 0.7, novelty: 0.5 }
const bland: ContentSalience = { salience: 0.25, socialSalience: 0.15, novelty: 0.5 }

describe('durability', () => {
  it('nO_gATING => exactly 1 for every memory', () => {
    expect(durability(salient, NO_GATING)).toBe(1)
    expect(durability(bland, NO_GATING)).toBe(1)
  })
  it('dEFAULT_GATING: salient > bland > 1', () => {
    expect(durability(salient, DEFAULT_GATING)).toBeGreaterThan(durability(bland, DEFAULT_GATING))
    expect(durability(salient, DEFAULT_GATING)).toBeGreaterThan(1)
  })
})

describe('decayExponent', () => {
  it('nO_GATING ignores salience entirely (== baseDecay)', () => {
    expect(decayExponent(0.9, 0.35, NO_GATING)).toBeCloseTo(0.35)
    expect(decayExponent(0.0, 0.35, NO_GATING)).toBeCloseTo(0.35)
  })
  it('dEFAULT_GATING: lower salience decays faster (higher exponent)', () => {
    expect(decayExponent(0.1, 0.35, DEFAULT_GATING)).toBeGreaterThan(decayExponent(0.9, 0.35, DEFAULT_GATING))
  })
})

describe('retrievalBreadth', () => {
  it('maps to the novelty coefficient (curiosity from content)', () => {
    expect(retrievalBreadth(NO_GATING)).toBe(0)
    expect(retrievalBreadth(DEFAULT_GATING)).toBeCloseTo(0.3)
  })
})
