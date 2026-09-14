import type { SkillRecord } from './types'

import { describe, expect, it } from 'vitest'

import {
  computeLearningLoopTable,
  computeSelfVerificationDiagnostics,
  computeTwoByTwo,

} from './types'

/**
 * Helper: build a fully-typed SkillRecord with sane defaults so the tests can
 * focus on the fields that matter for each case.
 */
function make(
  partial: Partial<SkillRecord> & Pick<SkillRecord, 'skillId' | 'name' | 'domain'>,
): SkillRecord {
  return {
    createdAt: 1_700_000_000_000,
    callCount: 0,
    successCount: 0,
    failureCount: 0,
    status: 'active',
    ...partial,
  }
}

describe('computeLearningLoopTable', () => {
  it('returns 4 cells whose precision is finite — the core regression test', () => {
    const records: SkillRecord[] = [
      // (selfVerification OFF, envFeedback OFF) — naïve accumulation baseline
      make({ skillId: 'a', name: 'a', domain: 'game', callCount: 2, successCount: 1 }),
      // (selfVerification OFF, envFeedback ON)
      make({
        skillId: 'b',
        name: 'b',
        domain: 'game',
        callCount: 2,
        successCount: 1,
        envFeedback: { enabled: true },
      }),
      // (selfVerification ON, envFeedback OFF) — naïve self-report (no environment feedback)
      make({
        skillId: 'c',
        name: 'c',
        domain: 'game',
        callCount: 4,
        successCount: 3,
        selfVerification: { verdict: 'pass', enabled: true },
      }),
      // (selfVerification ON, envFeedback ON) — full closed loop, then retired
      make({
        skillId: 'd',
        name: 'd',
        domain: 'game',
        callCount: 4,
        successCount: 4,
        status: 'retired',
        selfVerification: { verdict: 'pass', enabled: true },
        envFeedback: { enabled: true, appliedAt: 1_700_000_000_001 },
      }),
    ]

    const cells = computeLearningLoopTable(records)
    expect(cells).toHaveLength(4)

    // Every cell's headline metric must be a real number — NOT NaN. This is the
    // property the old domain-based 2×2 failed to guarantee (3/4 of its cells
    // were NaN, so no interaction effect could be estimated).
    for (const c of cells) {
      expect(Number.isFinite(c.precision)).toBe(true)
      expect(Number.isNaN(c.retiredRate)).toBe(false)
    }
  })

  it('default (no domain) aggregates oracle domains and is never empty', () => {
    // Records live in the `executable` oracle domain. A hardcoded 'game' default
    // would have returned an empty table here; the fixed default must pool all
    // oracle-bearing domains (executable + game) instead.
    const records: SkillRecord[] = [
      make({ skillId: 'e1', name: 'e1', domain: 'executable', callCount: 2, successCount: 1 }),
      make({ skillId: 'e2', name: 'e2', domain: 'executable', callCount: 2, successCount: 2, envFeedback: { enabled: true } }),
      make({ skillId: 'e3', name: 'e3', domain: 'executable', callCount: 3, successCount: 3, selfVerification: { verdict: 'pass', enabled: true } }),
      make({ skillId: 'e4', name: 'e4', domain: 'executable', callCount: 3, successCount: 3, selfVerification: { verdict: 'pass', enabled: true }, envFeedback: { enabled: true } }),
    ]
    const cells = computeLearningLoopTable(records)
    expect(cells).toHaveLength(4)
    for (const c of cells) {
      expect(Number.isFinite(c.precision)).toBe(true)
      expect(Number.isNaN(c.retiredRate)).toBe(false)
    }
    // All four cells observed at least one executable-domain skill.
    expect(cells.every(c => c.count > 0)).toBe(true)
  })

  it('shows envFeedback=ON retires more than envFeedback=OFF', () => {
    const records: SkillRecord[] = [
      make({ skillId: 'a', name: 'a', domain: 'game', callCount: 2, successCount: 1 }),
      make({
        skillId: 'b',
        name: 'b',
        domain: 'game',
        callCount: 2,
        successCount: 2,
        selfVerification: { verdict: 'pass', enabled: true },
      }),
      make({
        skillId: 'c',
        name: 'c',
        domain: 'game',
        callCount: 2,
        successCount: 1,
        envFeedback: { enabled: true },
      }),
      make({
        skillId: 'd',
        name: 'd',
        domain: 'game',
        callCount: 2,
        successCount: 2,
        status: 'retired',
        retirementReason: 'low-precision',
        selfVerification: { verdict: 'pass', enabled: true },
        envFeedback: { enabled: true },
      }),
    ]

    const cells = computeLearningLoopTable(records)
    // Aggregate retired rate per envFeedback column.
    const colRetiredRate = (ef: boolean) => {
      const col = cells.filter(c => c.envFeedbackEnabled === ef)
      const count = col.reduce((acc, c) => acc + c.count, 0)
      const retired = col.reduce((acc, c) => acc + c.retiredRate * c.count, 0)
      return retired / count
    }
    expect(colRetiredRate(true)).toBeGreaterThan(colRetiredRate(false))
  })
})

describe('computeSelfVerificationDiagnostics', () => {
  it('computes the hallucination rate on records with self-verdict + execution', () => {
    const records: SkillRecord[] = [
      make({ skillId: 'g1', name: 'g1', domain: 'game', selfVerification: { verdict: 'pass', enabled: true }, execution: { ok: true, executedAt: 1, attempt: 1 } }),
      make({ skillId: 'g2', name: 'g2', domain: 'game', selfVerification: { verdict: 'pass', enabled: true }, execution: { ok: true, executedAt: 1, attempt: 1 } }),
      make({ skillId: 'g3', name: 'g3', domain: 'game', selfVerification: { verdict: 'pass', enabled: true }, execution: { ok: true, executedAt: 1, attempt: 1 } }),
      // the single self-passed-but-failed skill -> 1/4 = 0.25
      make({ skillId: 'b1', name: 'b1', domain: 'game', selfVerification: { verdict: 'pass', enabled: true }, execution: { ok: false, executedAt: 1, attempt: 1 } }),
    ]

    const d = computeSelfVerificationDiagnostics(records)
    expect(d.n).toBe(4)
    expect(d.hallucinationRate).toBeCloseTo(0.25, 5)
    expect(d.agreement).toBeCloseTo(0.75, 5)
    // No self-fail record => miss rate is undefined (NaN), which is correct.
    expect(Number.isNaN(d.missRate)).toBe(true)
  })

  it('is empty (n=0, NaN rates) when no record has both self-verdict and execution', () => {
    const records: SkillRecord[] = [
      // self-verdict but no execution — cannot be diagnosed
      make({ skillId: 'a', name: 'a', domain: 'game', selfVerification: { verdict: 'pass', enabled: true } }),
      // execution but no self-verdict — cannot be diagnosed
      make({ skillId: 'b', name: 'b', domain: 'game', execution: { ok: true, executedAt: 1, attempt: 1 } }),
    ]
    const d = computeSelfVerificationDiagnostics(records)
    expect(d.n).toBe(0)
    expect(Number.isNaN(d.hallucinationRate)).toBe(true)
  })
})

describe('computeTwoByTwo (deprecated, backward compatible)', () => {
  it('still yields NaN for the conversation cell and a real rate for game', () => {
    const records: SkillRecord[] = [
      make({
        skillId: 'g1',
        name: 'mine',
        domain: 'game',
        selfVerification: { verdict: 'pass', enabled: true },
        execution: { ok: false, executedAt: 1, attempt: 1 },
      }),
      make({
        skillId: 'c1',
        name: 'comfort',
        domain: 'conversation',
        selfVerification: { verdict: 'pass', enabled: true },
        // no execution: conversation has no oracle
      }),
    ]

    const cells = computeTwoByTwo(records)
    expect(cells).toHaveLength(4)

    const gameOn = cells.find(c => c.domain === 'game' && c.selfVerificationEnabled)
    const convOn = cells.find(c => c.domain === 'conversation' && c.selfVerificationEnabled)
    expect(gameOn?.count).toBe(1)
    expect(gameOn?.hallucinationRate).toBe(1)
    expect(convOn?.count).toBe(1)
    // The conversation cell can never produce a hallucination rate — which is
    // precisely why the deprecated table is unusable for interaction testing.
    expect(Number.isNaN(convOn?.hallucinationRate ?? Number.NaN)).toBe(true)
  })
})
