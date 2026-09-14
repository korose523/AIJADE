import { describe, expect, it } from 'vitest'

import { retrievalStrength } from './forgetting'
import { DEFAULT_FORGETTING, DEFAULT_GATING, NO_GATING } from './types'

const f = DEFAULT_FORGETTING
const item = { createdAt: 0, accessCount: 0, baseStrength: 1, durability: 2.07 }
const YEAR = f.ageScaleMs * 365

describe('retrievalStrength', () => {
  it('decreases with age', () => {
    const s0 = retrievalStrength(item, 0, f, DEFAULT_GATING, 0.5)
    const s1 = retrievalStrength(item, YEAR, f, DEFAULT_GATING, 0.5)
    expect(s1).toBeLessThan(s0)
  })
  it('higher durability => stronger under DEFAULT_GATING', () => {
    const low = { ...item, durability: 1 }
    const high = { ...item, durability: 2.07 }
    expect(retrievalStrength(high, YEAR, f, DEFAULT_GATING, 0.5)).toBeGreaterThan(
      retrievalStrength(low, YEAR, f, DEFAULT_GATING, 0.5),
    )
  })
  it('with salience=1 (fully salient) ON and OFF give identical strength (salience=1 removes the salience-driven decay modulation)', () => {
    const a = retrievalStrength(item, YEAR, f, DEFAULT_GATING, 1)
    const b = retrievalStrength(item, YEAR, f, NO_GATING, 1)
    expect(a).toBeCloseTo(b, 6)
  })
  it('lower salience decays faster: ON(salience=0) < ON(salience=1) at long horizon', () => {
    const lowSal = retrievalStrength(item, YEAR, f, DEFAULT_GATING, 0)
    const highSal = retrievalStrength(item, YEAR, f, DEFAULT_GATING, 1)
    expect(lowSal).toBeLessThan(highSal)
  })
  it('spacing effect strengthens frequently retrieved items', () => {
    const once = { ...item, accessCount: 0 }
    const often = { ...item, accessCount: 10 }
    expect(retrievalStrength(often, YEAR, f, NO_GATING, 0.5)).toBeGreaterThan(
      retrievalStrength(once, YEAR, f, NO_GATING, 0.5),
    )
  })
})
