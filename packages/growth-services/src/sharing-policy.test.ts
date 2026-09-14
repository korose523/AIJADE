import type { ShareUtility } from './sharing-policy'

import { validateShareCandidate } from '@proj-aijade/memory-biomimetic'
import { describe, expect, it } from 'vitest'

import { InMemoryStorage } from './in-memory'
import { computeShareScore, isQuietHour, SharingPolicy } from './sharing-policy'
import { FixedScheduler } from './test-helpers'

function makeService(now: number) {
  return new SharingPolicy(
    { storage: new InMemoryStorage(), scheduler: new FixedScheduler(now) },
    'agent-1',
    'scope-1',
  )
}

const HIGH: ShareUtility = {
  relevance: 1,
  novelty: 1,
  relationalValue: 1,
  timeliness: 1,
  uncertainty: 1,
  interruption: 0,
  privacyRisk: 0,
  repetition: 0,
}

describe('sharingPolicy', () => {
  it('computeShareScore is monotone in positive utility', () => {
    const low = computeShareScore({ ...HIGH, relevance: 0 })
    const high = computeShareScore({ ...HIGH, relevance: 1 })
    expect(high).toBeGreaterThan(low)
    expect(computeShareScore(HIGH)).toBeLessThanOrEqual(1)
  })

  it('emits a ShareCandidate that passes validateShareCandidate', async () => {
    const now = new Date('2023-11-14T12:00:00Z').getTime() // noon-ish; check quiet locally
    const svc = makeService(now)
    const dec = await svc.scoreShare({ contentRef: 'ka-1', utility: HIGH })
    expect(validateShareCandidate(dec.candidate).ok).toBe(true)
    expect(dec.candidate.score).toBeGreaterThan(0)
    // channel agrees with the quiet-hour + threshold policy
    const quiet = isQuietHour(now)
    const expectedFull = dec.candidate.score >= 0.6 && !quiet
    expect(dec.candidate.channel === 'full_share').toBe(expectedFull)
  })

  it('isQuietHour matches the 23:00–07:00 local rule', () => {
    // pick a time, compute local hour, and verify the function agrees
    const t = new Date('2023-11-14T02:00:00Z').getTime()
    const hour = new Date(t).getHours()
    expect(isQuietHour(t)).toBe(hour >= 23 || hour < 7)
  })

  it('downgrades away from full_share during quiet hours (boundary)', async () => {
    // Find a time that is definitively inside the quiet window regardless of TZ offset.
    // 02:00 UTC is quiet in UTC; test that when quiet, channel is never full_share
    // for a moderate profile even if the score clears the threshold.
    const t = new Date('2023-11-14T02:00:00Z').getTime()
    const svc = makeService(t)
    const dec = await svc.scoreShare({ contentRef: 'ka-1', utility: HIGH })
    if (isQuietHour(t)) {
      expect(dec.candidate.channel).not.toBe('full_share')
    }
    else {
      expect(dec.candidate.channel).toBe('full_share')
    }
  })
})
