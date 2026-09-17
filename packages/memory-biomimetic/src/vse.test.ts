import type { EvaluationEvidencePack } from './contracts-v8'
import type { CandidateVersion } from './vse'

import { describe, expect, it } from 'vitest'

import {
  assertEvolvable,
  automationAllowed,
  canPromote,
  EVOLUTION_PIPELINE,
  nextEvolutionStage,
  satisfiesEvolutionConstraints,
  selectCandidateVersion,
  stableVseBucket,
} from './vse'

function pack(over: Partial<EvaluationEvidencePack> = {}): EvaluationEvidencePack {
  return {
    id: 'eep-1',
    schema: 'aijade.evaluation_evidence_pack@1',
    proposalRef: 'ep-1',
    unitContractPropertyTests: { passed: true, total: 10, failed: 0 },
    createdAt: 1000,
    ...over,
  }
}

describe('vSE — grading & automation ceiling (§51.1)', () => {
  it('keeps user assignments stable and prefers user identity over session identity', () => {
    const userBucket = stableVseBucket({ userId: 'user-1', sessionId: 'session-a' })
    expect(stableVseBucket({ userId: 'user-1', sessionId: 'session-b' })).toBe(userBucket)
    expect(stableVseBucket({ sessionId: 'session-a' })).not.toBe(userBucket)
    expect(userBucket).toBeGreaterThanOrEqual(0)
    expect(userBucket).toBeLessThan(1)
  })

  it('requires a real user or session identity for routing', () => {
    expect(() => stableVseBucket({})).toThrow(/userId or sessionId/)
  })

  it('e0 auto, E2 sandbox+sign, E3 full test, E4 human review, E5 forbidden', () => {
    expect(automationAllowed('E0')).toBe('auto')
    expect(automationAllowed('E2')).toBe('sandbox_sign_gray')
    expect(automationAllowed('E3')).toBe('full_test_review')
    expect(automationAllowed('E4')).toBe('human_review_required')
    expect(automationAllowed('E5')).toBe('forbidden')
  })
  it('e1–E3 are evolvable; E4/E5 are not autonomously modifiable', () => {
    expect(assertEvolvable('E1').ok).toBe(true)
    expect(assertEvolvable('E3').ok).toBe(true)
    expect(assertEvolvable('E4').ok).toBe(false)
    expect(assertEvolvable('E5').ok).toBe(false)
  })
})

describe('vSE — pipeline state machine (§51.3)', () => {
  it('advances through the full pipeline in order', () => {
    let s = EVOLUTION_PIPELINE[0] as any
    for (let i = 1; i < EVOLUTION_PIPELINE.length; i++) {
      s = nextEvolutionStage(s, 'advance')
      expect(s).toBe(EVOLUTION_PIPELINE[i])
    }
    expect(s).toBe('RUNTIME_MONITORING')
  })
  it('keep only valid from RUNTIME_MONITORING', () => {
    expect(nextEvolutionStage('RUNTIME_MONITORING', 'keep')).toBe('KEPT')
    expect(nextEvolutionStage('CANARY_RELEASE', 'keep')).toBeNull()
  })
  it('rollback from any stage; terminal states reject further events', () => {
    expect(nextEvolutionStage('SECURITY_SANDBOX', 'rollback')).toBe('ROLLED_BACK')
    expect(nextEvolutionStage('KEPT', 'advance')).toBeNull()
    expect(nextEvolutionStage('ROLLED_BACK', 'advance')).toBeNull()
  })
})

describe('vSE — promotion gate (§51.3)', () => {
  it('passes when core tests pass and optional gates pass', () => {
    expect(canPromote(pack())).toEqual({ ok: true })
    expect(canPromote(pack({ securitySandbox: { passed: true, escapes: 0 } }))).toEqual({ ok: true })
  })
  it('blocks when core tests fail', () => {
    const r = canPromote(pack({ unitContractPropertyTests: { passed: false, total: 10, failed: 3 } }))
    expect(r.ok).toBe(false)
  })
  it('blocks on any failing optional gate', () => {
    expect(canPromote(pack({ securitySandbox: { passed: false, escapes: 1 } })).ok).toBe(false)
    expect(canPromote(pack({ adversarialEval: { passed: false, findings: 2 } })).ok).toBe(false)
    expect(canPromote(pack({ historicalReplay: { passed: false, regressions: 1 } })).ok).toBe(false)
  })
})

describe('vSE — candidate selection (§51.4)', () => {
  function cand(over: Partial<CandidateVersion> = {}): CandidateVersion {
    return {
      id: 'v1',
      deltaQuality: 0.5,
      deltaLatency: 0.1,
      deltaCost: 0.1,
      risk: 0.1,
      complexity: 0.1,
      drift: 0.1,
      safety: 0.9,
      baselineSafety: 0.8,
      coreInvariantsHold: true,
      rollbackAvailable: true,
      ...over,
    }
  }

  it('selects the highest-objective feasible candidate', () => {
    const better = cand({ id: 'v2', deltaQuality: 0.9 })
    const best = selectCandidateVersion([cand({ id: 'v1' }), better])
    expect(best?.id).toBe('v2')
  })

  it('filters out candidates that reduce safety', () => {
    const unsafe = cand({ id: 'bad', safety: 0.5, baselineSafety: 0.8, deltaQuality: 99 })
    const best = selectCandidateVersion([unsafe, cand({ id: 'ok' })])
    expect(best?.id).toBe('ok')
  })

  it('filters out candidates breaking core invariants or lacking rollback', () => {
    const noInvariant = cand({ id: 'a', coreInvariantsHold: false, deltaQuality: 99 })
    const noRollback = cand({ id: 'b', rollbackAvailable: false, deltaQuality: 99 })
    expect(selectCandidateVersion([noInvariant, noRollback])).toBeNull()
  })

  it('returns null when nothing is feasible (keep baseline)', () => {
    expect(selectCandidateVersion([cand({ coreInvariantsHold: false })])).toBeNull()
  })

  it('satisfiesEvolutionConstraints encodes the three hard constraints', () => {
    expect(satisfiesEvolutionConstraints(cand())).toBe(true)
    expect(satisfiesEvolutionConstraints(cand({ safety: 0.1 }))).toBe(false)
    expect(satisfiesEvolutionConstraints(cand({ rollbackAvailable: false }))).toBe(false)
  })
})
