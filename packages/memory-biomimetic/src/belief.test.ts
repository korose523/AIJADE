import { describe, expect, it } from 'vitest'

import { applyRevision, createBelief, nextBeliefStatus, retract, revisionDelta } from './belief'
import { BioticMemory } from './store'
import { DEFAULT_BELIEF_CONFIG } from './types'

const cfg = DEFAULT_BELIEF_CONFIG

/** Fresh hypothesis belief with prior 0.5 (logit 0). */
function freshBelief(id = 'b1', evidenceIds: string[] = ['src1']): ReturnType<typeof createBelief> {
  return createBelief(
    { id, proposition: 'p', scope: 'global', owner: 'agent', evidenceIds, at: 1000 },
    cfg,
  )
}

describe('createBelief', () => {
  it('starts at the prior confidence and sits in hypothesis status', () => {
    const b = freshBelief()
    expect(b.confidence).toBeCloseTo(0.5, 6)
    expect(b.logit).toBeCloseTo(0, 6)
    expect(b.status).toBe('hypothesis')
    expect(b.supportLogit).toBe(0)
    expect(b.counterLogit).toBe(0)
    expect(b.evidenceIds).toEqual(['src1'])
  })
})

describe('revisionDelta — evidence transaction math', () => {
  it('adds supporting logit mass: Σ r_k·ℓ_k', () => {
    const d = revisionDelta(
      [{ id: 'e1', reliability: 1, likelihood: 2 }],
      [],
      cfg,
    )
    // 1 * 2 = 2 ; no counter
    expect(d.delta).toBeCloseTo(2, 6)
    expect(d.support).toBeCloseTo(2, 6)
    expect(d.counter).toBeCloseTo(0, 6)
    expect(d.clamped).toBe(false)
  })

  it('subtracts counter-evidence mass (magnitude, always negative)', () => {
    const d = revisionDelta(
      [],
      [{ id: 'c1', reliability: 1, likelihood: 2 }],
      cfg,
    )
    // counter is a positive magnitude that is subtracted → delta = -2
    expect(d.support).toBeCloseTo(0, 6)
    expect(d.counter).toBeCloseTo(2, 6)
    expect(d.delta).toBeCloseTo(-2, 6)
  })

  it('never lets a negative counter likelihood flip into an addition', () => {
    // Counter likelihood is clamped to [0, maxAbs]; a negative input becomes 0,
    // not a spurious positive contribution.
    const d = revisionDelta(
      [],
      [{ id: 'c1', reliability: 1, likelihood: -5 }],
      cfg,
    )
    expect(d.clamped).toBe(true)
    expect(d.counter).toBeCloseTo(0, 6)
    expect(d.delta).toBeCloseTo(0, 6)
  })

  it('clamps reliability to [0,1] and likelihood to ±maxAbs, and records it', () => {
    const d = revisionDelta(
      [{ id: 'e1', reliability: 1.5, likelihood: 5 }],
      [],
      cfg,
    )
    // r 1.5 -> 1 ; l 5 -> 2 ; realised term = 1 * 2 = 2 (not 7.5)
    expect(d.delta).toBeCloseTo(2, 6)
    expect(d.clamped).toBe(true)
    expect(d.reliabilities).toEqual([1])
    expect(d.rationale).toContain('clamped')
  })
})

describe('nextBeliefStatus thresholds', () => {
  it('retracts when confidence at/below the retract threshold', () => {
    expect(nextBeliefStatus(0.1, 2, 4, cfg)).toBe('retracted')
  })
  it('contests when counter carries ≥ contestedRatio of the logit mass', () => {
    // support 2, counter 2 → share 0.5 >= 0.5
    expect(nextBeliefStatus(0.5, 2, 2, cfg)).toBe('contested')
  })
  it('accepts when confident and not contested', () => {
    expect(nextBeliefStatus(0.8, 3, 0, cfg)).toBe('accepted')
  })
  it('otherwise stays hypothesis', () => {
    expect(nextBeliefStatus(0.5, 1, 0, cfg)).toBe('hypothesis')
  })
})

describe('applyRevision — supporting-only crosses into accepted', () => {
  it('a single strong supporting item pushes confidence above the accept threshold', () => {
    const b0 = freshBelief()
    expect(b0.status).toBe('hypothesis')
    const { belief: b1, revision } = applyRevision(
      b0,
      { id: 'r1', at: 2000, evidence: [{ id: 'e1', reliability: 1, likelihood: 2 }], actor: 'agent' },
      cfg,
    )
    // logit 0 -> 2 ; conf = sigmoid(2) ≈ 0.8808
    expect(b1.logit).toBeCloseTo(2, 6)
    expect(b1.confidence).toBeCloseTo(0.8808, 3)
    expect(b1.status).toBe('accepted')
    expect(b1.supportLogit).toBeCloseTo(2, 6)
    expect(b1.counterLogit).toBe(0)
    // audit record is complete and monotonic
    expect(revision.deltaLogit).toBeCloseTo(2, 6)
    expect(revision.logitBefore).toBeCloseTo(0, 6)
    expect(revision.logitAfter).toBeCloseTo(2, 6)
    expect(revision.clamped).toBe(false)
    expect(revision.actor).toBe('agent')
  })
})

describe('applyRevision — counter-evidence lowers confidence and contests', () => {
  it('enough counter mass drops confidence and flips accepted → contested', () => {
    const b0 = freshBelief()
    const { belief: accepted } = applyRevision(
      b0,
      { id: 'r1', at: 2000, evidence: [{ id: 'e1', reliability: 1, likelihood: 2 }], actor: 'agent' },
      cfg,
    )
    expect(accepted.status).toBe('accepted')
    const confBefore = accepted.confidence

    // two counter items of unit mass each → counter mass 2 == support mass 2 → share 0.5
    const { belief: contested, revision } = applyRevision(
      accepted,
      {
        id: 'r2',
        at: 3000,
        counterEvidence: [
          { id: 'c1', reliability: 1, likelihood: 1 },
          { id: 'c2', reliability: 1, likelihood: 1 },
        ],
        actor: 'agent',
      },
      cfg,
    )
    // logit 2 -> 0 ; conf = 0.5 (dropped from 0.8808)
    expect(contested.confidence).toBeLessThan(confBefore)
    expect(contested.logit).toBeCloseTo(0, 6)
    expect(contested.confidence).toBeCloseTo(0.5, 6)
    expect(contested.status).toBe('contested')
    expect(contested.supportLogit).toBeCloseTo(2, 6)
    expect(contested.counterLogit).toBeCloseTo(2, 6)
    expect(revision.deltaLogit).toBeCloseTo(-2, 6)
  })
})

describe('applyRevision — enough counter-evidence retracts', () => {
  it('drives confidence at/below the retract threshold → retracted', () => {
    const b0 = freshBelief()
    const { belief: accepted } = applyRevision(
      b0,
      { id: 'r1', at: 2000, evidence: [{ id: 'e1', reliability: 1, likelihood: 2 }], actor: 'agent' },
      cfg,
    )
    const { belief: contested } = applyRevision(
      accepted,
      {
        id: 'r2',
        at: 3000,
        counterEvidence: [
          { id: 'c1', reliability: 1, likelihood: 1 },
          { id: 'c2', reliability: 1, likelihood: 1 },
        ],
        actor: 'agent',
      },
      cfg,
    )
    expect(contested.status).toBe('contested')

    // add one more unit-2 counter item → counter 4, support 2 → logit -2 → conf ≈ 0.1192 ≤ 0.2
    const { belief: retracted } = applyRevision(
      contested,
      { id: 'r3', at: 4000, counterEvidence: [{ id: 'c3', reliability: 1, likelihood: 2 }], actor: 'agent' },
      cfg,
    )
    expect(retracted.logit).toBeCloseTo(-2, 6)
    expect(retracted.confidence).toBeCloseTo(0.1192, 3)
    expect(retracted.status).toBe('retracted')
    expect(retracted.counterLogit).toBeCloseTo(4, 6)
  })
})

describe('retract — explicit, non-silent, auditable', () => {
  it('records why, sets a validity end, and never mutates the prior confidence silently', () => {
    const b0 = freshBelief()
    const confBefore = b0.confidence
    const { belief: b1, revision } = retract(
      b0,
      { id: 'ret1', at: 5000, actor: 'user', reason: 'superseded by study X' },
    )
    expect(b1.status).toBe('retracted')
    expect(b1.validTo).toBe(5000)
    expect(b1.confidence).toBeCloseTo(confBefore, 6) // confidence preserved; status carries the meaning
    expect(revision.deltaLogit).toBe(0)
    expect(revision.rationale).toContain('retracted')
    expect(revision.rationale).toContain('superseded by study X')
    expect(revision.actor).toBe('user')
  })
})

describe('determinism', () => {
  it('identical inputs produce identical outputs', () => {
    const run = () => {
      const b0 = freshBelief('dup')
      const r1 = applyRevision(
        b0,
        { id: 'r1', at: 2000, evidence: [{ id: 'e1', reliability: 0.8, likelihood: 1.5 }], actor: 'agent' },
        cfg,
      )
      const r2 = applyRevision(
        r1.belief,
        { id: 'r2', at: 3000, counterEvidence: [{ id: 'c1', reliability: 0.6, likelihood: 1 }], actor: 'agent' },
        cfg,
      )
      return r2.belief
    }
    const a = run()
    const b = run()
    expect(a).toEqual(b)
    expect(a.logit).toBeCloseTo(b.logit, 12)
    expect(a.confidence).toBeCloseTo(b.confidence, 12)
  })
})

describe('belief-graph integration via BioticMemory (v7 §10.2)', () => {
  it('rejects a sourceless belief and records the rejection', () => {
    const m = new BioticMemory()
    const before = m.beliefs.length
    const res = m.proposeBelief({ proposition: 'no source here', evidenceIds: [] })
    expect(res.ok).toBe(false)
    expect(m.beliefs.length).toBe(before) // nothing entered
    expect(m.beliefRejections.length).toBe(1)
    expect(m.beliefRejections[0].reason).toContain('no source')
  })

  it('proposes, revises, retracts, and filters via activeBeliefs', () => {
    const m = new BioticMemory()
    const p = m.proposeBelief({ proposition: 'A causes B', evidenceIds: ['obs1'], actor: 'agent' })
    expect(p.ok).toBe(true)
    if (!p.ok)
      return
    expect(m.beliefs.length).toBe(1)
    expect(m.activeBeliefs().length).toBe(1)

    const rev = m.reviseBelief(p.belief.id, {
      evidence: [{ id: 'obs2', reliability: 1, likelihood: 2 }],
      actor: 'agent',
    })
    expect(rev.ok).toBe(true)
    if (!rev.ok)
      return
    expect(rev.belief.status).toBe('accepted')
    expect(rev.belief.confidence).toBeCloseTo(0.8808, 3)
    expect(m.beliefRevisions.length).toBe(1)

    const ret = m.retractBelief(p.belief.id, 'falsified by replication', 'user')
    expect(ret.ok).toBe(true)
    if (!ret.ok)
      return
    expect(ret.belief.status).toBe('retracted')
    expect(m.beliefRevisions.length).toBe(2)
    // retracted belief is no longer "active"
    expect(m.activeBeliefs().length).toBe(0)
  })

  it('respects the validity window in activeBeliefs', () => {
    const m = new BioticMemory(undefined, 1000)
    const p = m.proposeBelief({ proposition: 'timed', evidenceIds: ['src'], validTo: 5000 })
    expect(p.ok).toBe(true)
    if (!p.ok)
      return
    expect(m.activeBeliefs().length).toBe(1)
    m.setNow(6000) // moved past validTo
    expect(m.activeBeliefs().length).toBe(0)
  })
})
