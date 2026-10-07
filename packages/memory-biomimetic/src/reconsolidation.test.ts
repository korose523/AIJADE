import type { ContradictionDetector, ReconsolidationVerdict } from './reconsolidation'
import type { SemanticFact } from './types'

import { describe, expect, it } from 'vitest'

import {

  DEFAULT_RECONSOLIDATION,
  NoOpDetector,
  ReconsolidationEngine,

} from './reconsolidation'
import { NEUTRAL_AFFECT } from './types'

function mkFact(id = 'f1'): SemanticFact {
  return {
    id,
    content: 'old',
    derivedFrom: ['e1'],
    createdAt: 0,
    lastAccessedAt: 0,
    accessCount: 0,
    confidence: 1,
    baseStrength: 1,
    durability: 1,
    contextTags: [],
    salience: 1,
    affect: NEUTRAL_AFFECT,
    memoryType: 'semantic',
    status: 'active',
    validTime: {},
  }
}

const ENABLED = { enabled: true, labileWindowMs: 1000, cooldownMs: 500, maxVersions: 10 }

const contradictionDetector: ContradictionDetector = {
  evaluate: (): ReconsolidationVerdict => ({
    kind: 'contradiction',
    confidence: 0.9,
    proposedContent: 'new',
    proposedConfidence: 0.8,
  }),
}

describe('reconsolidationEngine', () => {
  it('is a no-op when disabled', () => {
    const e = new ReconsolidationEngine({ ...DEFAULT_RECONSOLIDATION, enabled: false })
    const { event } = e.reconsolidate(mkFact(), 'candidate', 0)
    expect(event).toBeNull()
  })

  it('marks labile within window and expires after', () => {
    const e = new ReconsolidationEngine(ENABLED)
    e.markLabile('f1', 0)
    expect(e.isLabile('f1', 500)).toBe(true)
    expect(e.isLabile('f1', 2000)).toBe(false)
  })

  it('applies a contradiction verdict and bumps version', () => {
    const e = new ReconsolidationEngine(ENABLED, contradictionDetector)
    e.markLabile('f1', 0)
    const { fact, event } = e.reconsolidate(mkFact(), 'candidate', 100)
    expect(event).not.toBeNull()
    expect(event?.kind).toBe('contradiction')
    expect(fact.content).toBe('new')
    expect(fact.confidence).toBe(0.8)
    expect(fact.reconsolidation?.version).toBe(1)
  })

  it('noOpDetector never mutates', () => {
    const e = new ReconsolidationEngine(ENABLED, NoOpDetector)
    e.markLabile('f1', 0)
    const { event } = e.reconsolidate(mkFact(), 'x', 100)
    expect(event).toBeNull()
  })

  it('ignores facts that are not labile', () => {
    const e = new ReconsolidationEngine(ENABLED, contradictionDetector)
    // not marked labile
    const { event } = e.reconsolidate(mkFact(), 'x', 0)
    expect(event).toBeNull()
  })

  it('respects cooldown (no thrashing)', () => {
    const updateDetector: ContradictionDetector = {
      evaluate: (): ReconsolidationVerdict => ({
        kind: 'update',
        confidence: 1,
        proposedContent: 'v',
        proposedConfidence: 1,
      }),
    }
    const e = new ReconsolidationEngine(ENABLED, updateDetector)
    e.markLabile('f1', 0)
    e.reconsolidate(mkFact(), 'a', 100)
    const before = e.getAuditTrail().length
    const { event } = e.reconsolidate(mkFact(), 'b', 200) // within cooldown 500
    expect(event).toBeNull()
    expect(e.getAuditTrail().length).toBe(before)
  })

  it('caps history at maxVersions', () => {
    const updateDetector: ContradictionDetector = {
      evaluate: (): ReconsolidationVerdict => ({
        kind: 'update',
        confidence: 1,
        proposedContent: 'v',
        proposedConfidence: 1,
      }),
    }
    const e = new ReconsolidationEngine(
      { enabled: true, labileWindowMs: 10_000, cooldownMs: 0, maxVersions: 2 },
      updateDetector,
    )
    e.markLabile('f1', 0)
    e.reconsolidate(mkFact(), 'a', 1)
    e.reconsolidate(mkFact(), 'b', 2)
    const { event } = e.reconsolidate(mkFact(), 'c', 3)
    expect(event).toBeNull() // capped at version 2
    expect(e.getAuditTrail()).toHaveLength(2)
  })
})
