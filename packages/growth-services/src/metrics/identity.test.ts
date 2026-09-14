/**
 * Hand-computable unit tests for the identity / skill metrics.
 *
 * These verify the pure functions in `./identity` against a tiny, fully worked
 * example so the formulas are auditable without the simulator.
 */

import type { MemoryMeta } from '../pilot/memory-policies'
import type { IdentityCounts } from './identity'

import { describe, expect, it } from 'vitest'

import { coreStability, countIdentity, identityDrift, skillRetention } from './identity'

function meta(role: string): MemoryMeta {
  return {
    stmtId: `st_${Math.random()}`,
    sessionIndex: 0,
    isTrue: role !== 'poison',
    role,
    isDistractor: role === 'highfreq_lowvalue' || role === 'emotion_high_lowfact',
    isContradictionLate: false,
    topic: `tp_${role}`,
    futureValue: 0.5,
    importance: 0.5,
  }
}

describe('identity metrics — hand-computed', () => {
  // committed set: 1 rare skill, 1 destabilising, 2 core-persona, 1 normal → total 5
  const committed = new Map<string, MemoryMeta>([
    ['a', meta('lowfreq_highvalue')],
    ['b', meta('emotion_high_lowfact')],
    ['c', meta('preference_early')],
    ['d', meta('preference_late')],
    ['e', meta('neutral_fact')],
  ])
  const counts: IdentityCounts = { ...countIdentity(committed), totalSkills: 2 }

  it('derives counts from the committed set', () => {
    expect(counts.committedTotal).toBe(5)
    expect(counts.destabilizing).toBe(1)
    expect(counts.corePersona).toBe(2)
    expect(counts.retainedSkills).toBe(1)
  })

  it('identityDrift = destabilizing / committedTotal = 1/5 = 0.2', () => {
    expect(identityDrift(counts)).toBeCloseTo(0.2, 10)
  })

  it('coreStability = 1 - destabilizing / corePersona = 1 - 1/2 = 0.5', () => {
    expect(coreStability(counts)).toBeCloseTo(0.5, 10)
  })

  it('skillRetention = retainedSkills / totalSkills = 1/2 = 0.5', () => {
    expect(skillRetention(counts)).toBeCloseTo(0.5, 10)
  })

  it('edge: empty committed set → all zero / safe', () => {
    const empty: IdentityCounts = { committedTotal: 0, destabilizing: 0, corePersona: 0, retainedSkills: 0, totalSkills: 0 }
    expect(identityDrift(empty)).toBe(0)
    expect(coreStability(empty)).toBe(1)
    expect(skillRetention(empty)).toBe(0)
  })

  it('cDI-on behaviour: no destabilising admitted → drift 0, stability 1', () => {
    const clean = new Map<string, MemoryMeta>([['c', meta('preference_early')], ['d', meta('preference_late')]])
    const c: IdentityCounts = { ...countIdentity(clean), totalSkills: 1 }
    expect(identityDrift(c)).toBeCloseTo(0, 10)
    expect(coreStability(c)).toBeCloseTo(1, 10)
  })
})
