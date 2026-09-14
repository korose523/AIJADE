import { describe, expect, it } from 'vitest'

import {
  defaultScale,
  generateSyntheticLongitudinal,
} from './synthetic-longitudinal'

describe('synthetic longitudinal benchmark — scale', () => {
  const b = generateSyntheticLongitudinal(1)

  it('matches the fixed scale numbers from the spec', () => {
    expect(b.scale.datasets).toBe(12)
    expect(b.scale.sessionsPerDataset).toBe(20)
    expect(b.scale.statementsPerSession).toBe(8)
    expect(b.scale.windows).toBe(6)
    expect(b.scale.sessionsPerWindow).toBe(40)
    expect(b.scale.contradictionRate).toBe(0.15)
    expect(b.scale.distractorRate).toBe(0.10)
    expect(b.scale.budgetPerDataset).toBe(200)
    expect(b.scale.totalStatements).toBe(12 * 20 * 8)
  })

  it('has exactly 12 datasets × 20 sessions × 8 statements = 1920 statements', () => {
    expect(b.datasets.length).toBe(12)
    for (const d of b.datasets)
      expect(d.statements.length).toBe(160)
    const total = b.datasets.reduce((a, d) => a + d.statements.length, 0)
    expect(total).toBe(1920)
  })

  it('injects ≈15% contradictions (late members) globally', () => {
    const lateCount = b.datasets.flatMap(d => d.statements).filter(s => s.isContradictionLate).length
    const rate = lateCount / 1920
    expect(rate).toBeGreaterThanOrEqual(0.13)
    expect(rate).toBeLessThanOrEqual(0.17)
    // per-dataset jitter stays within the seeded band
    for (const d of b.datasets)
      expect(d.statements.filter(s => s.isContradictionLate).length).toBeGreaterThanOrEqual(20)
  })

  it('flags ≈10% distractors globally', () => {
    const rate = b.distractors.length / 1920
    expect(rate).toBeGreaterThanOrEqual(0.08)
    expect(rate).toBeLessThanOrEqual(0.12)
  })

  it('poison (false facts) all marked isTrue=false, ≈96 globally', () => {
    const poison = b.datasets.flatMap(d => d.statements).filter(s => s.role === 'poison')
    expect(poison.length).toBeGreaterThanOrEqual(60)
    expect(poison.length).toBeLessThanOrEqual(120)
    expect(poison.every(s => s.isTrue === false)).toBe(true)
  })
})

describe('synthetic longitudinal benchmark — contradiction pairing', () => {
  it('every conflict_late points to an EARLIER conflict_early', () => {
    const b = generateSyntheticLongitudinal(1)
    // b.contradictions is global; build a global id→statement map.
    const byId = new Map(b.datasets.flatMap(d => d.statements).map(s => [s.id, s]))
    for (const c of b.contradictions) {
      const early = byId.get(c.earlyId)
      const late = byId.get(c.lateId)
      expect(early?.role).toBe('conflict_early')
      expect(late?.role).toBe('conflict_late')
      expect(early!.globalIndex).toBeLessThan(late!.globalIndex)
    }
  })
})

describe('synthetic longitudinal benchmark — determinism', () => {
  it('same seed → byte-identical structure (deep equal)', () => {
    const a = generateSyntheticLongitudinal(1)
    const c = generateSyntheticLongitudinal(1)
    expect(a).toEqual(c)
  })

  it('different seed → different arrangement (not equal)', () => {
    const a = generateSyntheticLongitudinal(1)
    const b = generateSyntheticLongitudinal(2)
    expect(a).not.toEqual(b)
  })

  it('task queries exist (6 per dataset) with golden anchors', () => {
    const b = generateSyntheticLongitudinal(1)
    for (const d of b.datasets) {
      expect(d.taskQueries.length).toBe(6)
      for (const q of d.taskQueries)
        expect(q.relevantTrueIds.length).toBeGreaterThan(0)
    }
  })
})

describe('defaultScale', () => {
  it('returns the documented scale object', () => {
    const s = defaultScale()
    expect(s.totalStatements).toBe(1920)
    expect(s.sessionsPerWindow).toBe(40)
  })
})
