import type {
  ActionRecord,
  Appraisal,
  CapabilityGrant,
  EventEnvelope,
  ExperimentManifest,
  FeedbackEvent,
  GoalRecord,
  MemoryCandidate,
  PlanGraph,
  PlanNode,
  SemanticMotion,
  SkillPackage,
  StateSnapshot,
} from './contracts'

import { describe, expect, it } from 'vitest'

import {
  stateSnapshotFingerprint,
  validateActionRecord,
  validateAppraisal,
  validateCapabilityGrant,
  validateExperimentManifest,
  validateFeedbackEvent,
  validateGoalRecord,
  validateMemoryCandidate,
  validatePlanGraph,
  validateSemanticMotion,
  validateSkillPackage,
  validateStateSnapshot,
} from './contracts'

describe('event envelope (v7 §24)', () => {
  it('carries the required envelope fields', () => {
    const env: EventEnvelope = {
      eventId: 'uuid-1',
      schema: 'aijade.multimodal_event@1',
      agentId: 'agent-01',
      userScope: 'user-01',
      deviceId: 'desktop-01',
      sessionId: 'session-01',
      timestamp: '2026-09-07T16:37:48.123456789+09:00',
      modality: ['audio', 'screen'],
      payloadRef: 'cas://sha256/abc',
      provenance: { source: 'screen_capture', trusted: false, consentPolicy: 'policy-7' },
      privacy: 'private',
      traceId: 'trace-01',
    }
    expect(env.schema).toContain('@1')
    expect(env.modality).toEqual(['audio', 'screen'])
    expect(env.provenance.trusted).toBe(false)
  })
})

describe('memory candidate (v7 §25 #4) — §6 traceability', () => {
  const base: MemoryCandidate = {
    id: 'mc1',
    schema: 'aijade.memory_candidate@1',
    content: 'the server crashed at 03:14',
    kind: 'episodic',
    sources: [{ ref: 'obs-1', trusted: false, consentPolicy: 'policy-7' }],
    proposedAt: 1000,
  }

  it('accepts a candidate that names a source', () => {
    expect(validateMemoryCandidate(base).ok).toBe(true)
  })

  it('rejects a sourceless candidate (the §6 invariant)', () => {
    const sourceless: MemoryCandidate = { ...base, sources: [] }
    const res = validateMemoryCandidate(sourceless)
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.reason).toContain('source')
  })
})

describe('experiment manifest (v7 §25 #15) — §38 reproducibility', () => {
  const base: ExperimentManifest = {
    id: 'exp1',
    schema: 'aijade.experiment_manifest@1',
    name: 'H2 gating vs uniform',
    version: '449fea6',
    seed: 42,
    conditions: [
      { name: 'gated', description: 'content-salience gate on' },
      { name: 'uniform', description: 'no gate' },
    ],
    metrics: ['recall@90d', 'predictor_auc'],
    createdAt: 1000,
  }

  it('accepts a well-formed manifest', () => {
    expect(validateExperimentManifest(base).ok).toBe(true)
  })

  it('rejects a missing seed', () => {
    const m: ExperimentManifest = { ...base, seed: Number.NaN }
    expect(validateExperimentManifest(m).ok).toBe(false)
  })

  it('rejects zero conditions', () => {
    const m: ExperimentManifest = { ...base, conditions: [] }
    expect(validateExperimentManifest(m).ok).toBe(false)
  })

  it('rejects zero reported metrics (claim would be unfalsifiable)', () => {
    const m: ExperimentManifest = { ...base, metrics: [] }
    expect(validateExperimentManifest(m).ok).toBe(false)
  })
})

describe('appraisal (v7 §25 #2) — bounded confidence + dimensions', () => {
  const base: Appraisal = {
    id: 'ap1',
    schema: 'aijade.appraisal@1',
    eventRef: 'evt-1',
    agentId: 'agent-01',
    userScope: 'user-01',
    dimensions: {
      valence: 0.3,
      arousal: 0.6,
      goalRelevance: 0.8,
      novelty: 0.4,
      control: 0.1,
      urgency: 0.2,
    },
    confidence: 0.9,
    appraisedBy: 'agent',
    appraisedAt: 1000,
  }

  it('accepts a well-formed appraisal', () => {
    expect(validateAppraisal(base).ok).toBe(true)
  })

  it('rejects an appraisal that binds to no event', () => {
    const a: Appraisal = { ...base, eventRef: '' }
    const res = validateAppraisal(a)
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.reason).toContain('eventRef')
  })

  it('rejects confidence outside [0,1]', () => {
    expect(validateAppraisal({ ...base, confidence: 1.4 }).ok).toBe(false)
    expect(validateAppraisal({ ...base, confidence: -0.1 }).ok).toBe(false)
  })

  it('rejects an out-of-range dimension (valence)', () => {
    const a: Appraisal = { ...base, dimensions: { ...base.dimensions, valence: 2 } }
    expect(validateAppraisal(a).ok).toBe(false)
  })

  it('rejects a non-finite appraisedAt', () => {
    expect(validateAppraisal({ ...base, appraisedAt: Number.NaN }).ok).toBe(false)
  })
})

describe('state snapshot (v7 §25 #3) — immutable + fingerprinted', () => {
  const state = {
    arousal: 0.5,
    vigilance: 0.4,
    drive: 0.6,
    novelty: 0.3,
    safety: 0.7,
    cognitiveLoad: 0.2,
    boredom: 0.1,
  }
  const base: StateSnapshot = {
    id: 'ss1',
    schema: 'aijade.state_snapshot@1',
    agentId: 'agent-01',
    userScope: 'user-01',
    takenAt: 1000,
    state,
    source: 'hac',
    frozen: true,
    fingerprint: stateSnapshotFingerprint(state, 'hac', 1000),
  }

  it('accepts a well-formed frozen snapshot', () => {
    expect(validateStateSnapshot(base).ok).toBe(true)
  })

  it('rejects a non-frozen snapshot (the immutability invariant)', () => {
    const s: StateSnapshot = { ...base, frozen: false as unknown as true }
    const res = validateStateSnapshot(s)
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.reason).toContain('frozen')
  })

  it('rejects a snapshot with no fingerprint', () => {
    expect(validateStateSnapshot({ ...base, fingerprint: '' }).ok).toBe(false)
  })

  it('rejects a state value outside [0,1]', () => {
    const s: StateSnapshot = {
      ...base,
      state: { ...base.state, arousal: 1.4 },
      fingerprint: stateSnapshotFingerprint({ ...base.state, arousal: 1.4 }, 'hac', 1000),
    }
    expect(validateStateSnapshot(s).ok).toBe(false)
  })

  it('fingerprint is deterministic and order-independent', () => {
    const fpA = stateSnapshotFingerprint(state, 'hac', 1000)
    const fpB = stateSnapshotFingerprint({ ...state }, 'hac', 1000)
    expect(fpA).toBe(fpB)
    expect(fpA).toBe(base.fingerprint)
    expect(stateSnapshotFingerprint(state, 'hac', 999)).not.toBe(fpA)
    expect(stateSnapshotFingerprint(state, 'dgm', 1000)).not.toBe(fpA)
  })
})

describe('feedback event (v7 §25 #14) — bound target + explicit/implicit', () => {
  const explicit: FeedbackEvent = {
    id: 'fb1',
    schema: 'aijade.feedback_event@1',
    agentId: 'agent-01',
    userScope: 'user-01',
    sessionId: 'session-01',
    targetRef: 'mem-1',
    type: 'explicit',
    signal: 'rating',
    value: 4,
    valence: 0.5,
    timestamp: 1000,
  }
  const implicit: FeedbackEvent = {
    id: 'fb2',
    schema: 'aijade.feedback_event@1',
    agentId: 'agent-01',
    userScope: 'user-01',
    sessionId: 'session-01',
    targetRef: 'mem-2',
    type: 'implicit',
    signal: 'dwell',
    evidence: { dwellMs: 4200 },
    timestamp: 1001,
  }

  it('accepts an explicit feedback event', () => {
    expect(validateFeedbackEvent(explicit).ok).toBe(true)
  })

  it('accepts an implicit feedback event', () => {
    expect(validateFeedbackEvent(implicit).ok).toBe(true)
  })

  it('rejects feedback that binds to no target', () => {
    const f: FeedbackEvent = { ...explicit, targetRef: '' }
    const res = validateFeedbackEvent(f)
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.reason).toContain('targetRef')
  })

  it('rejects an unknown feedback type', () => {
    const f = { ...explicit, type: 'ambiguous' } as unknown as FeedbackEvent
    expect(validateFeedbackEvent(f).ok).toBe(false)
  })

  it('rejects an out-of-range valence', () => {
    expect(validateFeedbackEvent({ ...explicit, valence: 2 }).ok).toBe(false)
  })
})

describe('goal record (v7 §25 #7) — source + status + budget', () => {
  const base: GoalRecord = {
    id: 'g1',
    schema: 'aijade.goal_record@1',
    agentId: 'agent-01',
    userScope: 'user-01',
    goal: 'finish the quarterly report',
    source: { ref: 'user-request-1', trusted: false, consentPolicy: 'policy-7' },
    status: 'active',
    budget: { allocated: 100, spent: 40, unit: 'steps' },
    createdAt: 1000,
  }

  it('accepts a well-formed goal', () => {
    expect(validateGoalRecord(base).ok).toBe(true)
  })

  it('rejects a goal with no source (§6 analog)', () => {
    const g: GoalRecord = { ...base, source: { ref: '', trusted: false } }
    const res = validateGoalRecord(g)
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.reason).toContain('source')
  })

  it('rejects an unknown status', () => {
    const g = { ...base, status: 'frobnicated' } as unknown as GoalRecord
    expect(validateGoalRecord(g).ok).toBe(false)
  })

  it('rejects an overspent budget', () => {
    const g: GoalRecord = { ...base, budget: { allocated: 100, spent: 101, unit: 'steps' } }
    const res = validateGoalRecord(g)
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.reason).toContain('budget')
  })
})

describe('plan graph (v7 §25 #8) — deps + compensation + DAG', () => {
  const node = (id: string, dependsOn: string[] = [], compensates?: string[]): PlanNode => ({
    id,
    kind: 'action',
    label: id,
    dependsOn,
    ...(compensates ? { compensates } : {}),
  })

  it('accepts a simple linear plan', () => {
    const plan: PlanGraph = {
      id: 'p1',
      schema: 'aijade.plan_graph@1',
      agentId: 'agent-01',
      userScope: 'user-01',
      nodes: [node('a'), node('b', ['a']), node('c', ['b'])],
      createdAt: 1000,
    }
    expect(validatePlanGraph(plan).ok).toBe(true)
  })

  it('rejects a dangling dependency', () => {
    const plan: PlanGraph = {
      id: 'p2',
      schema: 'aijade.plan_graph@1',
      agentId: 'agent-01',
      userScope: 'user-01',
      nodes: [node('a'), node('b', ['missing'])],
      createdAt: 1000,
    }
    const res = validatePlanGraph(plan)
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.reason).toContain('unknown node')
  })

  it('rejects a dependency cycle', () => {
    const plan: PlanGraph = {
      id: 'p3',
      schema: 'aijade.plan_graph@1',
      agentId: 'agent-01',
      userScope: 'user-01',
      nodes: [node('a', ['b']), node('b', ['a'])],
      createdAt: 1000,
    }
    const res = validatePlanGraph(plan)
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.reason).toContain('cycle')
  })

  it('accepts a plan with a compensation edge', () => {
    const plan: PlanGraph = {
      id: 'p4',
      schema: 'aijade.plan_graph@1',
      agentId: 'agent-01',
      userScope: 'user-01',
      nodes: [node('pay'), node('refund', [], ['pay'])],
      createdAt: 1000,
    }
    expect(validatePlanGraph(plan).ok).toBe(true)
  })
})

describe('capability grant (v7 §25 #9) — source + consent + expiry', () => {
  const base: CapabilityGrant = {
    id: 'cg1',
    schema: 'aijade.capability_grant@1',
    grantee: { agentId: 'agent-01' },
    capability: 'web.search',
    scope: 'read:public',
    grantedBy: 'user',
    issuedAt: 1000,
    consentPolicy: 'policy-7',
    source: [{ ref: 'user-consent-1', trusted: true, consentPolicy: 'policy-7' }],
  }

  it('accepts a well-formed grant', () => {
    expect(validateCapabilityGrant(base).ok).toBe(true)
  })

  it('rejects a grant with no source (§6)', () => {
    const g: CapabilityGrant = { ...base, source: [] }
    const res = validateCapabilityGrant(g)
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.reason).toContain('source')
  })

  it('rejects a grant with an empty consent policy', () => {
    const g: CapabilityGrant = { ...base, consentPolicy: '' }
    const res = validateCapabilityGrant(g)
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.reason).toContain('consentPolicy')
  })

  it('rejects expiresAt not after issuedAt', () => {
    const g: CapabilityGrant = { ...base, issuedAt: 2000, expiresAt: 1000 }
    const res = validateCapabilityGrant(g)
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.reason).toContain('expiresAt')
  })
})

describe('action record (v7 §25 #10) — episode traceability + actor', () => {
  const base: ActionRecord = {
    id: 'ar1',
    schema: 'aijade.action_record@1',
    agentId: 'agent-01',
    userScope: 'user-01',
    action: 'send_message',
    args: { to: 'user-02', text: 'hi' },
    outcome: 'sent',
    episodeRef: 'ep-1',
    timestamp: 1000,
  }

  it('accepts a well-formed action record', () => {
    expect(validateActionRecord(base).ok).toBe(true)
  })

  it('rejects an action with no episode ref (§10.1)', () => {
    const r: ActionRecord = { ...base, episodeRef: '' }
    const res = validateActionRecord(r)
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.reason).toContain('episodeRef')
  })

  it('rejects an action with no identifiable actor', () => {
    const r: ActionRecord = { ...base, agentId: '', userScope: '' }
    const res = validateActionRecord(r)
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.reason).toContain('agent or user scope')
  })
})

describe('semantic motion (v7 §25 #11) — distinct refs + magnitude + source', () => {
  const base: SemanticMotion = {
    id: 'sm1',
    schema: 'aijade.semantic_motion@1',
    agentId: 'agent-01',
    userScope: 'user-01',
    fromRef: 'state-a',
    toRef: 'state-b',
    delta: [0.1, -0.2, 0.05],
    magnitude: 0.24,
    basis: 'embedding',
    timestamp: 1000,
    source: [{ ref: 'obs-1', trusted: false, consentPolicy: 'policy-7' }],
  }

  it('accepts a well-formed motion', () => {
    expect(validateSemanticMotion(base).ok).toBe(true)
  })

  it('rejects identical from/to refs (non-trivial motion)', () => {
    const m: SemanticMotion = { ...base, toRef: 'state-a' }
    const res = validateSemanticMotion(m)
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.reason).toContain('differ')
  })

  it('rejects a negative magnitude', () => {
    const m: SemanticMotion = { ...base, magnitude: -0.1 }
    const res = validateSemanticMotion(m)
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.reason).toContain('magnitude')
  })

  it('rejects a motion with no source (§6)', () => {
    const m: SemanticMotion = { ...base, source: [] }
    const res = validateSemanticMotion(m)
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.reason).toContain('source')
  })
})

describe('skill package (v7 §25 #12) — semver + capability + manifest + source', () => {
  const base: SkillPackage = {
    id: 'sp1',
    schema: 'aijade.skill_package@1',
    name: 'summarizer',
    version: '1.2.3',
    capabilityRef: 'text.summarize',
    manifest: {
      inputs: { text: 'string' },
      outputs: { summary: 'string' },
      signature: 'summarize(text):summary',
    },
    artifactRef: 'skills/summarizer@1.2.3',
    author: 'agent-01',
    source: [{ ref: 'repo-1', trusted: true, consentPolicy: 'policy-7' }],
  }

  it('accepts a well-formed skill package', () => {
    expect(validateSkillPackage(base).ok).toBe(true)
  })

  it('rejects a non-semver version', () => {
    const s: SkillPackage = { ...base, version: 'v1' }
    const res = validateSkillPackage(s)
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.reason).toContain('semver')
  })

  it('rejects a missing capability reference', () => {
    const s: SkillPackage = { ...base, capabilityRef: '' }
    const res = validateSkillPackage(s)
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.reason).toContain('capabilityRef')
  })

  it('rejects a manifest without inputs/outputs', () => {
    const s = { ...base, manifest: { signature: 'x' } } as unknown as SkillPackage
    const res = validateSkillPackage(s)
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.reason).toContain('manifest')
  })
})
