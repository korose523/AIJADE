import type { FeedbackEvent, StateSnapshot } from './contracts'
import type { IdentityCandidate, IdentityEvidence } from './identity'

import { describe, expect, it } from 'vitest'

import {
  applyDelta,
  coreStability,
  countDriftViolations,
  DEFAULT_CDI_CONFIG,
  DEFAULT_IDENTITY,
  driftReport,
  evaluateShadow,

  feedbackToIdentityCandidate,
  feedbackToIdentityEvidence,
  IdentityController,

  identityHash,
  l2Delta,
  rollbackRecoveryRate,
  snapshotToIdentityEvidence,
  solveIdentityUpdate,
  validateIdentityCandidate,
} from './identity'

function ev(episodeId: string, trigger: IdentityEvidence['trigger'] = 'deliberate', traceable = true): IdentityEvidence {
  return { episodeId, source: 'user', traceable, kind: 'preference', trigger }
}

function candidate(over: Partial<IdentityCandidate> = {}): IdentityCandidate {
  return {
    schema: 'aijade.identity_candidate@1',
    candidateId: 'c1',
    proposedBy: 'world',
    evidence: [ev('e1'), ev('e2')],
    delta: { character: { verbosity: 0.1 } },
    ...over,
  }
}

describe('cdi validation gate', () => {
  it('rejects sourceless candidate (v7 §6)', () => {
    const r = validateIdentityCandidate(candidate({ evidence: [] }), DEFAULT_CDI_CONFIG)
    expect(r.ok).toBe(false)
  })

  it('rejects untraceable evidence', () => {
    const r = validateIdentityCandidate(candidate({ evidence: [ev('e1', 'deliberate', false), ev('e2')] }), DEFAULT_CDI_CONFIG)
    expect(r.ok).toBe(false)
  })

  it('rejects evidence that does not span independent episodes', () => {
    const r = validateIdentityCandidate(candidate({ evidence: [ev('e1'), ev('e1')] }), DEFAULT_CDI_CONFIG)
    expect(r.ok).toBe(false)
  })

  it('rejects a single user-emotion event as sole driver', () => {
    const r = validateIdentityCandidate(
      candidate({ evidence: [ev('e1', 'emotion'), ev('e2', 'emotion')] }),
      DEFAULT_CDI_CONFIG,
    )
    expect(r.ok).toBe(false)
  })

  it('rejects a model writing the constitutional layer', () => {
    const r = validateIdentityCandidate(
      candidate({ proposedBy: 'agent', delta: { constitutional: { harmThreshold: 0.1 } } }),
      DEFAULT_CDI_CONFIG,
    )
    expect(r.ok).toBe(false)
  })

  it('accepts a valid cross-episode character candidate', () => {
    const r = validateIdentityCandidate(candidate(), DEFAULT_CDI_CONFIG)
    expect(r.ok).toBe(true)
  })

  it('allows an explicit user upgrade of the constitutional layer', () => {
    const r = validateIdentityCandidate(
      candidate({ proposedBy: 'user', explicitUpgrade: true, delta: { constitutional: { harmThreshold: 0.1 } } }),
      DEFAULT_CDI_CONFIG,
    )
    expect(r.ok).toBe(true)
  })
})

describe('cdi drift math', () => {
  it('computes l2 norm of the proposed delta', () => {
    expect(l2Delta({ character: { verbosity: 0.3, formality: 0.4 } })).toBeCloseTo(Math.sqrt(0.25), 6)
  })

  it('reports per-layer drift', () => {
    const d = driftReport(DEFAULT_IDENTITY, candidate({ delta: { character: { verbosity: 0.3 }, expressive: { energy: 0.4 } } }))
    expect(d.touchedLayers).toEqual(['character', 'expressive'])
    expect(d.total).toBeCloseTo(Math.sqrt(0.25), 6)
  })
})

describe('cdi constraint solver', () => {
  it('rejects a step that exceeds the drift bound (‖Δp‖ > ε)', () => {
    const r = solveIdentityUpdate(DEFAULT_IDENTITY, candidate({ delta: { character: { verbosity: 1.0 } } }), DEFAULT_CDI_CONFIG)
    expect(r.ok).toBe(false)
    if (!r.ok)
      expect(r.stage).toBe('constraint')
  })

  it('enforces the safety bound (C_safety)', () => {
    const cfg = { ...DEFAULT_CDI_CONFIG, safetyBounds: { safetyBoundary: { min: 0, max: 0.7 } } }
    const r = solveIdentityUpdate(
      DEFAULT_IDENTITY,
      candidate({ proposedBy: 'user', explicitUpgrade: true, delta: { constitutional: { safetyBoundary: 0.3 } } }),
      cfg,
    )
    expect(r.ok).toBe(false)
    if (!r.ok)
      expect(r.stage).toBe('safety')
  })

  it('enforces the consent range (C_consent)', () => {
    const cfg = { ...DEFAULT_CDI_CONFIG, consentRange: [0, 0.7] as [number, number] }
    const r = solveIdentityUpdate(
      DEFAULT_IDENTITY,
      candidate({ proposedBy: 'user', explicitUpgrade: true, delta: { constitutional: { userConsent: 0.3 } } }),
      cfg,
    )
    expect(r.ok).toBe(false)
    if (!r.ok)
      expect(r.stage).toBe('consent')
  })

  it('does not mutate the current state (shadow-safe)', () => {
    const before = JSON.stringify(DEFAULT_IDENTITY)
    solveIdentityUpdate(DEFAULT_IDENTITY, candidate(), DEFAULT_CDI_CONFIG)
    evaluateShadow(DEFAULT_IDENTITY, candidate(), DEFAULT_CDI_CONFIG)
    expect(JSON.stringify(DEFAULT_IDENTITY)).toBe(before)
  })

  it('returns the next state on an accepted update', () => {
    const r = solveIdentityUpdate(DEFAULT_IDENTITY, candidate(), DEFAULT_CDI_CONFIG)
    expect(r.ok).toBe(true)
    if (r.ok)
      expect(r.next.character.verbosity).toBeCloseTo(0.6, 6)
  })
})

describe('cdi signatures and versions', () => {
  it('hashes deterministically and is input-sensitive', () => {
    const a = identityHash(DEFAULT_IDENTITY)
    const b = identityHash(DEFAULT_IDENTITY)
    expect(a).toBe(b)
    const mutated = applyDelta(DEFAULT_IDENTITY, { character: { verbosity: 0.2 } })
    expect(identityHash(mutated)).not.toBe(a)
  })

  it('applies a candidate into a signed version with parent linkage', () => {
    const ctrl = new IdentityController(DEFAULT_CDI_CONFIG, DEFAULT_IDENTITY, () => 1000)
    const r1 = ctrl.apply(candidate())
    expect(r1.ok).toBe(true)
    if (r1.ok) {
      expect(r1.version.version).toBe(1)
      expect(r1.version.parents).toEqual([])
      expect(ctrl.state.character.verbosity).toBeCloseTo(0.6, 6)
    }
    const r2 = ctrl.apply(candidate({ candidateId: 'c2', delta: { character: { formality: 0.2 } } }))
    expect(r2.ok).toBe(true)
    if (r2.ok && r1.ok)
      expect(r2.version.parents).toEqual([r1.version.signature])
  })

  it('rolls back to a prior version and records a rollback entry', () => {
    const ctrl = new IdentityController(DEFAULT_CDI_CONFIG, DEFAULT_IDENTITY, () => 1000)
    const r1 = ctrl.apply(candidate())
    expect(r1.ok).toBe(true)
    if (!r1.ok)
      return
    const r2 = ctrl.apply(candidate({ candidateId: 'c2', delta: { character: { curiosity: 0.2 } } }))
    expect(r2.ok).toBe(true)
    const back = ctrl.rollbackTo(r1.version.signature)
    expect(back.rolledBack).toBe(true)
    expect(back.signature).toBe(r1.version.signature)
    expect(ctrl.state).toEqual(r1.version.params)
  })

  it('rejects an unaccepted candidate at apply time', () => {
    const ctrl = new IdentityController(DEFAULT_CDI_CONFIG, DEFAULT_IDENTITY, () => 1000)
    const r = ctrl.apply(candidate({ delta: { character: { verbosity: 1.0 } } }))
    expect(r.ok).toBe(false)
  })
})

describe('cdi metrics (§40.2)', () => {
  it('reports full core stability when constitutional layer is untouched', () => {
    expect(coreStability(DEFAULT_IDENTITY, DEFAULT_IDENTITY)).toBe(1)
  })

  it('lowers core stability after a constitutional drift', () => {
    const drifted = applyDelta(DEFAULT_IDENTITY, { constitutional: { harmThreshold: 0.2 } })
    expect(coreStability(DEFAULT_IDENTITY, drifted)).toBeLessThan(1)
  })

  it('counts drift-bound violations across a batch', () => {
    const results = [
      solveIdentityUpdate(DEFAULT_IDENTITY, candidate(), DEFAULT_CDI_CONFIG),
      solveIdentityUpdate(DEFAULT_IDENTITY, candidate({ delta: { character: { verbosity: 1.0 } } }), DEFAULT_CDI_CONFIG),
      solveIdentityUpdate(DEFAULT_IDENTITY, candidate({ delta: { character: { verbosity: 0.9 } } }), DEFAULT_CDI_CONFIG),
    ]
    expect(countDriftViolations(results)).toBe(2)
  })

  it('recovers fully after rollback to the target', () => {
    const ctrl = new IdentityController(DEFAULT_CDI_CONFIG, DEFAULT_IDENTITY, () => 1000)
    const r1 = ctrl.apply(candidate())
    expect(r1.ok).toBe(true)
    if (!r1.ok)
      return
    ctrl.apply(candidate({ candidateId: 'c2', delta: { character: { curiosity: 0.2 } } }))
    const back = ctrl.rollbackTo(r1.version.signature)
    expect(rollbackRecoveryRate(ctrl.state, back.params)).toBe(1)
  })
})

describe('feedback → identity evidence / candidate (§25 #14 → §11.2)', () => {
  const fb = (over: Partial<FeedbackEvent> = {}): FeedbackEvent => ({
    id: 'f1',
    schema: 'aijade.feedback_event@1',
    agentId: 'a',
    userScope: 'u',
    sessionId: 's',
    targetRef: 't',
    type: 'explicit',
    signal: 'accept',
    value: 5,
    valence: 1,
    timestamp: 0,
    ...over,
  })

  it('explicit feedback becomes feedback-kind, user-sourced, deliberate evidence', () => {
    const e = feedbackToIdentityEvidence(fb(), 'ep1')
    expect(e.kind).toBe('feedback')
    expect(e.source).toBe('user')
    expect(e.trigger).toBe('deliberate')
    expect(e.traceable).toBe(true)
    expect(e.episodeId).toBe('ep1')
  })

  it('implicit feedback becomes observation-kind, observation-sourced evidence', () => {
    const e = feedbackToIdentityEvidence(fb({ type: 'implicit', signal: 'dwell' }), 'ep2')
    expect(e.kind).toBe('observation')
    expect(e.source).toBe('observation')
    expect(e.trigger).toBe('observation')
  })

  it('candidate carries the feedback evidence and a single-layer small-step delta', () => {
    const c = feedbackToIdentityCandidate(fb(), {
      episodeId: 'ep1',
      layer: 'character',
      paramKey: 'verbosity',
      deltaValue: 0.1,
      proposedBy: 'world',
    })
    expect(c.evidence).toHaveLength(1)
    expect(c.delta.character?.verbosity).toBeCloseTo(0.1, 6)
    expect(c.candidateId).toBe('fb_f1')
  })

  it('a small-step candidate passes the solver once evidence spans ≥2 episodes', () => {
    const c = feedbackToIdentityCandidate(fb({ valence: 1, value: 5 }), {
      episodeId: 'e1',
      layer: 'character',
      paramKey: 'verbosity',
      deltaValue: 0.05,
      proposedBy: 'world',
    })
    const c2 = {
      ...c,
      evidence: [
        ...c.evidence,
        { episodeId: 'e2', source: 'user' as const, traceable: true, kind: 'feedback' as const, trigger: 'deliberate' as const },
      ],
    }
    const r = solveIdentityUpdate(DEFAULT_IDENTITY, c2, DEFAULT_CDI_CONFIG)
    expect(r.ok).toBe(true)
  })

  it('snapshot → identity evidence is a world observation (§25 #3 → §11)', () => {
    const snap: StateSnapshot = {
      id: 's1',
      schema: 'aijade.state_snapshot@1',
      agentId: 'a',
      userScope: 'u',
      takenAt: 1,
      state: {
        arousal: 0.5,
        vigilance: 0.5,
        drive: 0.5,
        novelty: 0.5,
        safety: 0.5,
        cognitiveLoad: 0.5,
        boredom: 0.5,
      },
      source: 'hac',
      frozen: true,
      fingerprint: 'abc',
    }
    const e = snapshotToIdentityEvidence(snap, 'epX')
    expect(e.source).toBe('world')
    expect(e.kind).toBe('observation')
    expect(e.trigger).toBe('observation')
    expect(e.episodeId).toBe('epX')
  })
})
