import type { Appraisal, FeedbackEvent } from './contracts'
import type { EndogenousState, HacConfig, ReplayCandidate, UtilityFeatures, WriteConstraints } from './hac'

import { describe, expect, it } from 'vitest'

import { stateSnapshotFingerprint, validateStateSnapshot } from './contracts'
import {
  appraisalToStimulus,
  canWriteHard,
  DEFAULT_HAC_CONFIG,

  feedbackToHacAction,
  HacController,
  homeostaticError,
  mulberry32,
  predictUtility,

  retrievalDegradation,
  selectReplay,
  stepState,

  writeDecision,
} from './hac'

function state(p: Partial<EndogenousState>): EndogenousState {
  return { a: 0.5, v: 0.5, d: 0.5, n: 0.5, s: 0.5, c: 0.5, b: 0.5, ...p }
}

function features(p: Partial<UtilityFeatures>): UtilityFeatures {
  return { I: 0.5, N: 0.5, R: 0.5, G: 0.5, P: 0.5, C: 0.5, Q: 0.5, ...p }
}

const okConstraints: WriteConstraints = {
  hasSource: true,
  userPolicyAllows: true,
  notPromptInjection: true,
  notDuplicate: true,
  typeValid: true,
  conflictFlagged: true,
  budgetRemaining: 10,
}

describe('stepState (§9.1)', () => {
  it('ablated mode freezes the state', () => {
    const cfg: HacConfig = { ...DEFAULT_HAC_CONFIG, dynamics: 'ablated' }
    const z0 = state({ a: 0.3 })
    const next = stepState(z0, state({ a: 1 }), state({ a: 0 }), cfg, mulberry32(1))
    expect(next.a).toBeCloseTo(0.3, 6)
  })

  it('moves toward stimulus and stays within bounds', () => {
    const cfg = DEFAULT_HAC_CONFIG
    const z0 = state({ a: 0.5 })
    // push stimulus high repeatedly; state should rise but never exceed zMax
    let z = z0
    for (let i = 0; i < 50; i++)
      z = stepState(z, state({ a: 1 }), state({ a: 0 }), cfg, mulberry32(i + 1))
    expect(z.a).toBeLessThanOrEqual(cfg.zMax)
    expect(z.a).toBeGreaterThan(0.5)
  })
})

describe('homeostaticError (§9.2)', () => {
  it('is zero at the setpoint', () => {
    const e = homeostaticError(state({ a: 0.5, c: 0.5 }), DEFAULT_HAC_CONFIG)
    expect(e.a).toBeCloseTo(0, 6)
    expect(e.c).toBeCloseTo(0, 6)
  })
  it('is positive when above setpoint, negative below', () => {
    const e = homeostaticError(state({ a: 0.8 }), DEFAULT_HAC_CONFIG)
    expect(e.a).toBeGreaterThan(0)
    const e2 = homeostaticError(state({ a: 0.2 }), DEFAULT_HAC_CONFIG)
    expect(e2.a).toBeLessThan(0)
  })
})

describe('predictUtility (§9.2)', () => {
  it('rewards informativeness/novelty/goal and penalises cost/risk', () => {
    const w = DEFAULT_HAC_CONFIG.utilityWeights
    const high = predictUtility(features({ I: 1, N: 1, C: 0, Q: 0 }), w)
    const low = predictUtility(features({ I: 0, N: 0, C: 1, Q: 1 }), w)
    expect(high).toBeGreaterThan(low)
  })
})

describe('canWriteHard (§9.3 hard constraints)', () => {
  it('passes when every condition holds', () => {
    expect(canWriteHard(okConstraints).ok).toBe(true)
  })
  it('reports the first failing condition', () => {
    const r1 = canWriteHard({ ...okConstraints, hasSource: false })
    expect(r1.ok).toBe(false)
    if (!r1.ok)
      expect(r1.reason).toContain('source')
    const r2 = canWriteHard({ ...okConstraints, budgetRemaining: 0 })
    expect(r2.ok).toBe(false)
    if (!r2.ok)
      expect(r2.reason).toContain('budget')
    const r3 = canWriteHard({ ...okConstraints, notPromptInjection: false })
    expect(r3.ok).toBe(false)
    if (!r3.ok)
      expect(r3.reason).toContain('injection')
  })
})

describe('writeDecision (§9.3 gate)', () => {
  it('forces p=0 when a hard constraint fails, ignoring the logistic', () => {
    const d = writeDecision(features({}), state({}), state({}), { ...okConstraints, hasSource: false }, DEFAULT_HAC_CONFIG)
    expect(d.hardOk).toBe(false)
    expect(d.p).toBe(0)
  })

  it('gate responds to features with the learned sign', () => {
    // only informativeness (I) rewarded and cost (C) penalised; rest neutral
    const cfg: HacConfig = {
      ...DEFAULT_HAC_CONFIG,
      gate: { w: [1, 0, 0, 0, 0, -2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], b: 0 },
    }
    const cheap = writeDecision(features({ I: 1, C: 0 }), state({}), state({}), okConstraints, cfg)
    const costly = writeDecision(features({ I: 1, C: 1 }), state({}), state({}), okConstraints, cfg)
    expect(cheap.p).toBeGreaterThan(costly.p)
    expect(cheap.p).toBeGreaterThan(0.5)
    expect(costly.p).toBeLessThan(0.5)
  })
})

describe('selectReplay (§9.4)', () => {
  it('matches brute force on a small instance', () => {
    const cands: ReplayCandidate[] = [
      { id: 'x', U: 0.9, D: 0.1, sim: { y: 0.9, z: 0.1 } },
      { id: 'y', U: 0.8, D: 0.2, sim: { x: 0.9, z: 0.8 } },
      { id: 'z', U: 0.7, D: 0.3, sim: { x: 0.1, y: 0.8 } },
    ]
    const rho = 0.5
    const greedy = selectReplay(cands, rho)
    // brute force all 2^3 subsets
    let best: string[] = []
    let bestScore = -Infinity
    for (let mask = 1; mask < 8; mask++) {
      const S = cands.filter((_, i) => mask & (1 << i)).map(c => c.id)
      let score = 0
      for (const id of S) {
        const c = cands.find(cc => cc.id === id)!
        score += c.U + c.D
      }
      for (let i = 0; i < S.length; i++) {
        for (let j = i + 1; j < S.length; j++) {
          const ci = cands.find(cc => cc.id === S[i])!
          score -= rho * (ci.sim[S[j]] ?? 0)
        }
      }
      if (score > bestScore) {
        bestScore = score
        best = S
      }
    }
    expect(greedy.sort()).toEqual(best.sort())
  })

  it('drops redundant items (high pairwise similarity)', () => {
    const cands: ReplayCandidate[] = [
      { id: 'x', U: 1, D: 0, sim: {} },
      { id: 'y', U: 1, D: 0, sim: { x: 1 } },
    ]
    const chosen = selectReplay(cands, 1)
    expect(chosen).toEqual(['x']) // y is redundant with x (penalty 1·1 = 1 cancels its gain)
  })
})

describe('retrievalDegradation (§9.5) — the necessary cost', () => {
  it('is deterministic for a fixed seed', () => {
    const r1 = mulberry32(7)
    const r2 = mulberry32(7)
    expect(retrievalDegradation(0.5, DEFAULT_HAC_CONFIG, r1)).toBeCloseTo(
      retrievalDegradation(0.5, DEFAULT_HAC_CONFIG, r2),
      12,
    )
  })

  it('variance grows with cognitive load c_t', () => {
    const n = 20000
    const sample = (c: number) => {
      const rng = mulberry32(12345)
      const xs: number[] = []
      for (let i = 0; i < n; i++)
        xs.push(retrievalDegradation(c, DEFAULT_HAC_CONFIG, rng))
      const mean = xs.reduce((s, x) => s + x, 0) / n
      const variance = xs.reduce((s, x) => s + (x - mean) ** 2, 0) / n
      return variance
    }
    const vLow = sample(0) // σ0² = 0.0025
    const vHigh = sample(1) // σ0² + σ1 = 0.0025 + 0.15 = 0.1525
    expect(vLow).toBeCloseTo(0.0025, 2)
    expect(vHigh).toBeCloseTo(0.1525, 2)
    expect(vHigh).toBeGreaterThan(vLow * 50)
  })

  it('high load measurably flips retrieval rankings — a real cost, not a gain', () => {
    // Two items: A true score 0.9, B true score 0.5 (gap 0.4).
    // Under low load the gap dominates; under high load noise can overturn it.
    const flips = (c: number) => {
      const rng = mulberry32(999)
      let count = 0
      const trials = 5000
      for (let t = 0; t < trials; t++) {
        const a = 0.9 + retrievalDegradation(c, DEFAULT_HAC_CONFIG, rng)
        const b = 0.5 + retrievalDegradation(c, DEFAULT_HAC_CONFIG, rng)
        if (b > a)
          count++
      }
      return count / trials
    }
    const low = flips(0)
    const high = flips(1)
    expect(low).toBeLessThan(0.01)
    expect(high).toBeGreaterThan(0.1)
    expect(high).toBeGreaterThan(low)
  })
})

describe('hacController', () => {
  it('exposes mutable state, error, decision and degradation', () => {
    const ctrl = new HacController(DEFAULT_HAC_CONFIG)
    const rng = mulberry32(3)
    ctrl.step(state({ a: 1 }), state({ a: 0 }), rng)
    expect(ctrl.state.a).toBeGreaterThan(0.5)
    const dec = ctrl.decide(features({ I: 1, C: 0 }), okConstraints)
    expect(dec.hardOk).toBe(true)
    expect(dec.p).toBeGreaterThan(0)
    const xi = ctrl.degradation(mulberry32(5))
    expect(Number.isFinite(xi)).toBe(true)
  })
})

describe('appraisalToStimulus (§25 #2 → §9.1)', () => {
  const appraisal = (d: Partial<Appraisal['dimensions']>): Appraisal => ({
    id: 'a1',
    schema: 'aijade.appraisal@1',
    eventRef: 'e1',
    agentId: 'x',
    userScope: 'u',
    dimensions: {
      valence: 0,
      arousal: 0.5,
      goalRelevance: 0.5,
      novelty: 0.5,
      control: 0,
      urgency: 0.5,
      ...d,
    },
    confidence: 1,
    appraisedBy: 'agent',
    appraisedAt: 0,
  })

  it('maps all appraisal dims onto the 7-dim stimulus monotonically and in-range', () => {
    const s = appraisalToStimulus(appraisal({
      valence: 1,
      arousal: 1,
      goalRelevance: 1,
      novelty: 1,
      control: 1,
      urgency: 1,
    }))
    expect(s.a).toBeCloseTo(1, 6) // arousal
    expect(s.v).toBeCloseTo(1, 6) // goalRelevance → vigilance
    expect(s.d).toBeCloseTo(1, 6) // valence(+1)/2 → drive
    expect(s.n).toBeCloseTo(1, 6) // novelty
    expect(s.s).toBeCloseTo(1, 6) // control(+1)/2 → safety
    expect(s.c).toBeCloseTo(1, 6) // urgency → cognitive load
    expect(s.b).toBeCloseTo(0, 6) // 1 − arousal → boredom
  })

  it('translates negative valence/control to the low end and clamps overflow', () => {
    const s = appraisalToStimulus(appraisal({
      valence: -1,
      arousal: 2,
      control: -1,
      goalRelevance: 0,
      novelty: 0,
      urgency: 0,
    }))
    expect(s.d).toBeCloseTo(0, 6) // valence −1 → drive 0
    expect(s.s).toBeCloseTo(0, 6) // control −1 → safety 0
    expect(s.a).toBeCloseTo(1, 6) // arousal 2 clamped to 1
  })
})

describe('feedbackToHacAction (§25 #14 → §9.2)', () => {
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

  it('positive explicit feedback raises safety and lowers load', () => {
    const act = feedbackToHacAction(fb({ type: 'explicit', signal: 'accept', value: 5, valence: 1 }))
    expect(act.s).toBeGreaterThan(0.5)
    expect(act.c).toBeLessThan(0.5)
  })

  it('negative feedback does the opposite', () => {
    const act = feedbackToHacAction(fb({ type: 'explicit', signal: 'decline', value: 1, valence: -1 }))
    expect(act.s).toBeLessThan(0.5)
    expect(act.c).toBeGreaterThan(0.5)
  })

  it('implicit feedback is observed but sign-neutral', () => {
    const act = feedbackToHacAction(fb({ type: 'implicit', signal: 'dwell', evidence: { dwellMs: 5000 }, value: undefined, valence: undefined }))
    expect(act.s).toBeCloseTo(0.5, 6)
    expect(act.c).toBeCloseTo(0.5, 6)
  })
})

describe('hacController appraisal + snapshot (§25 #2/#3)', () => {
  const appraisal = (d: Partial<Appraisal['dimensions']>): Appraisal => ({
    id: 'a1',
    schema: 'aijade.appraisal@1',
    eventRef: 'e1',
    agentId: 'x',
    userScope: 'u',
    dimensions: {
      valence: 0,
      arousal: 1,
      goalRelevance: 0.5,
      novelty: 0.5,
      control: 0,
      urgency: 0.5,
      ...d,
    },
    confidence: 1,
    appraisedBy: 'agent',
    appraisedAt: 0,
  })

  it('drives z_t from an appraisal through the stimulus channel only', () => {
    const ctrl = new HacController(DEFAULT_HAC_CONFIG)
    ctrl.stepAppraisal(appraisal({ arousal: 1 }), mulberry32(42))
    expect(ctrl.state.a).toBeGreaterThan(0.5)
  })

  it('is deterministic for a fixed seed', () => {
    const mk = (): EndogenousState => {
      const c = new HacController(DEFAULT_HAC_CONFIG)
      const r = mulberry32(42)
      for (let i = 0; i < 5; i++)
        c.stepAppraisal(appraisal({ arousal: 1 }), r)
      return c.state
    }
    const a = mk()
    const b = mk()
    expect(a.a).toBeCloseTo(b.a, 12)
  })

  it('snapshot is frozen, fingerprinted, and validates', () => {
    const ctrl = new HacController(DEFAULT_HAC_CONFIG)
    const snap = ctrl.snapshot('hac', 1000, 'agent', 'user')
    expect(snap.frozen).toBe(true)
    expect(snap.source).toBe('hac')
    expect(snap.fingerprint).toBe(stateSnapshotFingerprint(snap.state, 'hac', 1000))
    expect(validateStateSnapshot(snap).ok).toBe(true)
  })

  it('produces identical fingerprints for identical state+source+time', () => {
    const st = {
      arousal: 0.5,
      vigilance: 0.5,
      drive: 0.5,
      novelty: 0.5,
      safety: 0.5,
      cognitiveLoad: 0.5,
      boredom: 0.5,
    }
    expect(stateSnapshotFingerprint(st, 'hac', 7)).toBe(stateSnapshotFingerprint(st, 'hac', 7))
  })
})
