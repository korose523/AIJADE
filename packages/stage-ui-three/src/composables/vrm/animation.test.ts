import { describe, expect, it } from 'vitest'

import { mulberry32 } from '../../libs/determinism'
import { useBlink } from './animation'

/**
 * Drive useBlink with a fake VRM and record the wall-clock moments at which a
 * blink *starts* (blink value rises from 0). With a fixed seed/rng the schedule
 * of those moments must be identical across runs; with a different one it must
 * differ.
 */
function blinkStarts(opts: { seed?: number, rng?: () => number }, totalSeconds = 120): number[] {
  const starts: number[] = []
  let prev = 0
  let t = 0
  const delta = 1 / 60
  const vrm = {
    expressionManager: {
      setValue: (name: string, v: number) => {
        if (name === 'blink') {
          if (v > 0 && prev <= 0)
            starts.push(Number(t.toFixed(6)))
          prev = v
        }
      },
    },
  } as any
  const blink = useBlink(opts)
  while (t < totalSeconds) {
    blink.update(vrm, delta)
    t += delta
  }
  return starts
}

describe('useBlink determinism (replay contract)', () => {
  it('same seed -> identical blink schedule', () => {
    expect(blinkStarts({ seed: 1234 })).toEqual(blinkStarts({ seed: 1234 }))
  })

  it('different seed -> different blink schedule', () => {
    expect(blinkStarts({ seed: 1234 })).not.toEqual(blinkStarts({ seed: 5678 }))
  })

  it('an injected rng is reproducible and overrides the default seed', () => {
    expect(blinkStarts({ rng: mulberry32(0xBEEF) }))
      .toEqual(blinkStarts({ rng: mulberry32(0xBEEF) }))
    expect(blinkStarts({ rng: mulberry32(0xBEEF) }))
      .not.toEqual(blinkStarts({ rng: mulberry32(0xFACE) }))
  })
})
