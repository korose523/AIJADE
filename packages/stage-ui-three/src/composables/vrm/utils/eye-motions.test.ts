import { describe, expect, it } from 'vitest'

import { mulberry32 } from '../../../libs/determinism'
import { randomSaccadeInterval } from './eye-motions'

/** Draw `n` saccade intervals from a single seeded stream. */
function saccadeSequence(seed: number, n: number): number[] {
  const rng = mulberry32(seed)
  return Array.from({ length: n }, () => randomSaccadeInterval(rng))
}

describe('randomSaccadeInterval determinism (replay contract)', () => {
  it('same seed -> identical saccade sequence', () => {
    expect(saccadeSequence(7, 64)).toEqual(saccadeSequence(7, 64))
  })

  it('different seed -> different saccade sequence', () => {
    expect(saccadeSequence(7, 64)).not.toEqual(saccadeSequence(8, 64))
  })

  it('preserves the legacy behavior shape (bounds from EYE_SACCADE_INT_*)', () => {
    // First bucket base is 800ms, step is 400ms, and the top bucket base is
    // 800 + 9*400 = 4400ms, so every interval lies in [800, 4800).
    for (const v of saccadeSequence(7, 64)) {
      expect(v).toBeGreaterThanOrEqual(800)
      expect(v).toBeLessThan(4800)
    }
  })

  it('default (no-arg) path preserves the legacy bounds (shape unchanged)', () => {
    // The default path uses a fixed-seed module RNG, so it is reproducible by
    // construction. Here we just lock the legacy interval shape: every default
    // draw stays within [800, 4800) ms.
    for (const v of Array.from({ length: 32 }, () => randomSaccadeInterval())) {
      expect(v).toBeGreaterThanOrEqual(800)
      expect(v).toBeLessThan(4800)
    }
  })
})
