/**
 * v7 §9 — Homeostatic Active Consolidation (HAC).
 *
 * ⚠️ COMPATIBILITY GUARD (our H2c result): the 7-dim endogenous state `z_t` is a
 * computational* homeostatic variable (§9.1), NOT the hormone vector we already
 * proved (H2c) contributes ≈0 to recall gain. So `z_t` must NEVER feed memory
 * durability / salience — doing so would resurrect the discredited "hormone gain
 * knob" and trip v7 §42. `z_t` drives exactly two things:
 *   1. the WRITE gate `p_i^write` (§9.3) — whether a candidate is promoted to LTM;
 *   2. the retrieval DEGRADATION noise `ξ_i` (§9.5) — a *cost* that grows with
 *      cognitive load `c_t`, which is what makes HAC falsifiable rather than a
 *      bag of gain dials.
 *
 * Everything here is pure except the `HacController` wrapper, which holds mutable
 * `z_t` for a running agent. All randomness is seeded for reproducibility.
 */

import type { Appraisal, FeedbackEvent, StateSnapshot } from './contracts'

import { stateSnapshotFingerprint } from './contracts'

/** The seven homeostatic dimensions (§9.1). Computational, not biological. */
export type HacDim = 'a' | 'v' | 'd' | 'n' | 's' | 'c' | 'b'
export const HAC_DIMS: readonly HacDim[] = ['a', 'v', 'd', 'n', 's', 'c', 'b']

export type EndogenousState = Record<HacDim, number>
export type HomeostaticSetpoint = Record<HacDim, number>

/** Predicted future-utility features for one candidate memory (§9.2). */
export interface UtilityFeatures {
  /** Task informativeness. */
  I: number
  /** Novelty. */
  N: number
  /** Relational relevance. */
  R: number
  /** Future goal relevance. */
  G: number
  /** Predicted homeostatic-error reduction. */
  P: number
  /** Storage / retrieval cost. */
  C: number
  /** Evidence uncertainty or privacy risk. */
  Q: number
}

export interface HacWeights {
  alpha: number
  beta: number
  gamma: number
  delta: number
  eta: number
  lambda: number
  mu: number
}

export interface HacConfig {
  /** Versioned dynamics mode (v7 §9.1: matrices must be recorded & can be ablated). */
  dynamics: 'fixed' | 'learned' | 'ablated'
  /** State clip bounds. */
  zMin: number
  zMax: number
  /** Self-dynamics A, stimulus map B, action map C (each 7×7, row-major per dim). */
  A: number[][]
  B: number[][]
  C: number[][]
  /** Target setpoint z*. */
  setpoint: HomeostaticSetpoint
  /** Homeostatic-error weighting W_z (diagonal, per dim). */
  Wz: Record<HacDim, number>
  utilityWeights: HacWeights
  /** Write-gate logistic params: w has length 21 = [utility7 | state7 | error7]. */
  gate: { w: number[], b: number }
  /** §9.5 retrieval-degradation noise. */
  degradation: { sigma0: number, sigma1: number }
  /**
   * Opt-in. When false the store's existing content-salience gating ablation
   * (H2/H5) is untouched; HAC only activates if a caller enables it.
   */
  enabled: boolean
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function diag7(x: number): number[][] {
  return HAC_DIMS.map((_, i) => HAC_DIMS.map((_, j) => (i === j ? x : 0)))
}

function neutralState(cfg: Pick<HacConfig, 'zMin' | 'zMax'>): EndogenousState {
  const mid = (cfg.zMin + cfg.zMax) / 2
  return HAC_DIMS.reduce((acc, d) => {
    acc[d] = mid
    return acc
  }, {} as EndogenousState)
}

function matVec(M: number[][], v: EndogenousState): EndogenousState {
  const out = {} as EndogenousState
  HAC_DIMS.forEach((rowDim, i) => {
    let s = 0
    HAC_DIMS.forEach((colDim, j) => {
      s += M[i][j] * v[colDim]
    })
    out[rowDim] = s
  })
  return out
}

function clipState(z: EndogenousState, lo: number, hi: number): EndogenousState {
  return HAC_DIMS.reduce((acc, d) => {
    acc[d] = Math.min(hi, Math.max(lo, z[d]))
    return acc
  }, {} as EndogenousState)
}

function addState(...vs: EndogenousState[]): EndogenousState {
  return HAC_DIMS.reduce((acc, d) => {
    acc[d] = vs.reduce((s, v) => s + v[d], 0)
    return acc
  }, {} as EndogenousState)
}

// ---------------------------------------------------------------------------
// defaults
// ---------------------------------------------------------------------------

export const DEFAULT_HAC_CONFIG: HacConfig = {
  dynamics: 'fixed',
  zMin: 0,
  zMax: 1,
  // mild persistence, modest stimulus / action response
  A: diag7(0.9),
  B: diag7(0.1),
  C: diag7(0.1),
  setpoint: { a: 0.5, v: 0.5, d: 0.5, n: 0.5, s: 0.5, c: 0.5, b: 0.5 },
  Wz: { a: 1, v: 1, d: 1, n: 1, s: 1, c: 1, b: 1 },
  utilityWeights: { alpha: 1, beta: 1, gamma: 1, delta: 1, eta: 1, lambda: 1, mu: 1 },
  gate: { w: Array.from({ length: 21 } as ArrayLike<number>).fill(0.1), b: 0 },
  degradation: { sigma0: 0.05, sigma1: 0.15 },
  enabled: false,
}

// ---------------------------------------------------------------------------
// §9.1 state transition
// ---------------------------------------------------------------------------

/**
 * `z_{t+1} = clip(A·z_t + B·g(x_t) + C·u_t + ε_t, zMin, zMax)`.
 * `stimulus` = g(x_t), `action` = u_t. `rng` supplies process noise ε_t (seeded).
 * In 'ablated' mode the state is frozen (returns z_t unchanged) — the HAC ablation.
 */
export function stepState(
  z: EndogenousState,
  stimulus: EndogenousState,
  action: EndogenousState,
  cfg: HacConfig,
  rng: () => number,
): EndogenousState {
  if (cfg.dynamics === 'ablated')
    return { ...z }
  const eps = HAC_DIMS.reduce((acc, d) => {
    // small zero-mean process noise in [−0.02, 0.02]
    acc[d] = (rng() - 0.5) * 0.04
    return acc
  }, {} as EndogenousState)
  const next = addState(matVec(cfg.A, z), matVec(cfg.B, stimulus), matVec(cfg.C, action), eps)
  return clipState(next, cfg.zMin, cfg.zMax)
}

// ---------------------------------------------------------------------------
// §9.2 homeostatic error + utility
// ---------------------------------------------------------------------------

/** `e_t = W_z·(z_t − z*)`, per dimension. */
export function homeostaticError(z: EndogenousState, cfg: HacConfig): EndogenousState {
  return HAC_DIMS.reduce((acc, d) => {
    acc[d] = cfg.Wz[d] * (z[d] - cfg.setpoint[d])
    return acc
  }, {} as EndogenousState)
}

/** `U_i = αI + βN + γR + δG + ηP − λC − μQ` (§9.2). */
export function predictUtility(f: UtilityFeatures, w: HacWeights): number {
  return w.alpha * f.I + w.beta * f.N + w.gamma * f.R + w.delta * f.G + w.eta * f.P
    - w.lambda * f.C - w.mu * f.Q
}

// ---------------------------------------------------------------------------
// §9.3 consolidation gate + hard constraints
// ---------------------------------------------------------------------------

/** The seven hard pre-conditions for any write (§9.3). */
export interface WriteConstraints {
  hasSource: boolean
  userPolicyAllows: boolean
  notPromptInjection: boolean
  notDuplicate: boolean
  typeValid: boolean
  conflictFlagged: boolean
  /** Remaining write budget (>0 means room to write). */
  budgetRemaining: number
}

/** Pure check of the §9.3 hard constraints; returns the first failing reason. */
export function canWriteHard(c: WriteConstraints): { ok: true } | { ok: false, reason: string } {
  if (!c.hasSource)
    return { ok: false, reason: 'no source (v7 §6)' }
  if (!c.userPolicyAllows)
    return { ok: false, reason: 'user policy forbids' }
  if (!c.notPromptInjection)
    return { ok: false, reason: 'possible prompt injection' }
  if (!c.notDuplicate)
    return { ok: false, reason: 'duplicate' }
  if (!c.typeValid)
    return { ok: false, reason: 'type validation failed' }
  if (!c.conflictFlagged)
    return { ok: false, reason: 'conflict not flagged' }
  if (c.budgetRemaining <= 0)
    return { ok: false, reason: 'write budget exceeded' }
  return { ok: true }
}

/** Gate feature vector φ = [utility7 | state7 | error7]. */
export function gateFeatures(f: UtilityFeatures, z: EndogenousState, e: EndogenousState): number[] {
  return [f.I, f.N, f.R, f.G, f.P, f.C, f.Q, z.a, z.v, z.d, z.n, z.s, z.c, z.b, e.a, e.v, e.d, e.n, e.s, e.c, e.b]
}

function sigmoid01(x: number): number {
  return 1 / (1 + Math.exp(-x))
}

export interface WriteDecision {
  /** Logistic gate probability p_i^write ∈ [0,1]. */
  p: number
  /** True iff the §9.3 hard constraints all pass (independent of p). */
  hardOk: boolean
  /** Why hard constraints failed, if they did. */
  reason?: string
  phi: number[]
}

/**
 * `p_i^write = σ(wᵀφ(m_i,z_t,e_t) + b)`. If any hard constraint fails the gate is
 * forced to 0 — the hard rules dominate the learned gate (§9.3).
 */
export function writeDecision(
  f: UtilityFeatures,
  z: EndogenousState,
  e: EndogenousState,
  constraints: WriteConstraints,
  cfg: HacConfig,
): WriteDecision {
  const hard = canWriteHard(constraints)
  const phi = gateFeatures(f, z, e)
  if (!hard.ok) {
    return { p: 0, hardOk: false, reason: hard.reason, phi }
  }
  let dot = cfg.gate.b
  for (let i = 0; i < phi.length; i++)
    dot += cfg.gate.w[i] * phi[i]
  return { p: sigmoid01(dot), hardOk: true, phi }
}

// ---------------------------------------------------------------------------
// §9.4 active replay selection (greedy approximation)
// ---------------------------------------------------------------------------

export interface ReplayCandidate {
  id: string
  /** Predicted future utility U_i. */
  U: number
  /** Conflict value vs existing beliefs D_i. */
  D: number
  /** Similarity to every other candidate id. */
  sim: Record<string, number>
}

/**
 * `S* = argmax_S Σ(U_i+D_i) − ρ·Σ_{i≠j} sim(i,j)` (§9.4).
 * Exact is NP-hard; we greedily add the item with the best marginal gain until
 * none is positive. Deterministic given input order.
 */
export function selectReplay(
  candidates: ReplayCandidate[],
  rho: number,
  budget = candidates.length,
): string[] {
  const chosen: string[] = []
  const remaining = [...candidates]
  while (chosen.length < budget && remaining.length > 0) {
    let bestIdx = -1
    let bestGain = -Infinity
    for (let i = 0; i < remaining.length; i++) {
      const cand = remaining[i]
      let redundancy = 0
      for (const id of chosen)
        redundancy += cand.sim[id] ?? 0
      const gain = (cand.U + cand.D) - rho * redundancy
      if (gain > bestGain) {
        bestGain = gain
        bestIdx = i
      }
    }
    if (bestGain <= 0)
      break
    chosen.push(remaining[bestIdx].id)
    remaining.splice(bestIdx, 1)
  }
  return chosen
}

// ---------------------------------------------------------------------------
// §9.5 retrieval degradation — the necessary, falsifiable cost
// ---------------------------------------------------------------------------

/** Seeded uniform RNG (mulberry32) for reproducible noise. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6D2B79F5) | 0
    let t = (Math.imul(a ^ (a >>> 15), 1 | a))
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function sampleStandardNormal(rng: () => number): number {
  let u = 0
  let v = 0
  while (u === 0)
    u = rng()
  while (v === 0)
    v = rng()
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v)
}

/**
 * `ξ_i ~ N(0, σ0² + σ1·c_t)` (§9.5). The variance GROWS with cognitive load
 * `c_t`, so high load measurably degrades retrieval — this is the mechanism's
 * falsifiable cost, not a performance boost.
 */
export function retrievalDegradation(
  c_t: number,
  cfg: HacConfig,
  rng: () => number,
): number {
  const variance = cfg.degradation.sigma0 ** 2 + cfg.degradation.sigma1 * Math.max(0, c_t)
  return Math.sqrt(variance) * sampleStandardNormal(rng)
}

// ---------------------------------------------------------------------------
// §25 closed-loop adapters — Appraisal → z_t, z_t → StateSnapshot, Feedback → action
// ---------------------------------------------------------------------------

function clamp01(x: number): number {
  return Math.min(1, Math.max(0, x))
}

/**
 * Map a §25 `Appraisal` (#2) onto the 7-dim endogenous stimulus g(x_t) (§9.1).
 *
 * Every appraisal dimension is bounded into [0,1] so the stimulus is in-range by
 * construction (HAC clips anyway, but this keeps the mapping honest). The mapping
 * is monotonic and documented; it is itself an ablatable mechanism — swap this
 * function to ablate how an appraisal drives the state (v7 §38). Crucially it
 * feeds z_t only, never durability / salience (H2c guard preserved).
 */
export function appraisalToStimulus(appraisal: Appraisal): EndogenousState {
  const d = appraisal.dimensions
  const valence = (d.valence + 1) / 2 // [−1,1] → [0,1]
  const control = (d.control + 1) / 2 // [−1,1] → [0,1]
  return {
    a: clamp01(d.arousal), // arousal → arousal
    v: clamp01(d.goalRelevance), // goal relevance → vigilance
    d: clamp01(valence), // valence → drive (approach)
    n: clamp01(d.novelty), // novelty → novelty
    s: clamp01(control), // control → safety
    c: clamp01(d.urgency), // urgency → cognitive load
    b: clamp01(1 - d.arousal), // high arousal ⇒ low boredom
  }
}

/**
 * Map a §25 `FeedbackEvent` (#14) onto an HAC action u_t — the utility/action
 * half of the feedback loop (§9.2). Positive, explicit feedback nudges the
 * endogenous state toward a calmer setpoint (more safety, less load); negative
 * feedback does the opposite; implicit feedback is observed but sign-neutral.
 * Conservative and bounded — like every HAC input it is an ablatable default, not
 * a learned policy.
 */
export function feedbackToHacAction(feedback: FeedbackEvent): EndogenousState {
  const sign = feedback.valence !== undefined
    ? Math.sign(feedback.valence)
    : feedback.type === 'explicit'
      ? 1
      : 0
  const mag = feedback.value !== undefined
    ? clamp01(Math.abs(feedback.value) / 5) // e.g. a 1–5 rating
    : 0.2
  const delta = sign * mag
  const mid = (DEFAULT_HAC_CONFIG.zMin + DEFAULT_HAC_CONFIG.zMax) / 2
  return {
    a: mid,
    v: mid,
    d: mid,
    n: mid,
    s: clamp01(mid + delta), // positive ⇒ more safety
    c: clamp01(mid - delta), // positive ⇒ less load
    b: mid,
  }
}

/** Endogenous-state key order (a,v,d,n,s,c,b) → `StateSnapshot.state` key order. */
function endogenousToSnapshotState(z: EndogenousState): StateSnapshot['state'] {
  return {
    arousal: z.a,
    vigilance: z.v,
    drive: z.d,
    novelty: z.n,
    safety: z.s,
    cognitiveLoad: z.c,
    boredom: z.b,
  }
}

// ---------------------------------------------------------------------------
// controller wrapper (holds mutable z_t for a running agent)
// ---------------------------------------------------------------------------

export class HacController {
  private z: EndogenousState
  constructor(
    private readonly cfg: HacConfig,
    z?: EndogenousState,
  ) {
    this.z = z ?? neutralState(cfg)
  }

  get state(): EndogenousState {
    return { ...this.z }
  }

  /** Advance the endogenous state from a stimulus + action/feedback pair. */
  step(stimulus: EndogenousState, action: EndogenousState, rng: () => number): EndogenousState {
    this.z = stepState(this.z, stimulus, action, this.cfg, rng)
    return this.state
  }

  error(): EndogenousState {
    return homeostaticError(this.z, this.cfg)
  }

  decide(f: UtilityFeatures, constraints: WriteConstraints): WriteDecision {
    return writeDecision(f, this.z, this.error(), constraints, this.cfg)
  }

  /** Cognitive-load-driven retrieval noise (§9.5), sampled at retrieve time. */
  degradation(rng: () => number, c_t: number = this.z.c): number {
    return retrievalDegradation(c_t, this.cfg, rng)
  }

  /**
   * Advance the endogenous state from a §25 `Appraisal` (#2). The action is
   * neutral so the appraisal drives z_t *only* through the stimulus channel — the
   * H2c-safe path (§9.1): appraisal never touches durability / salience.
   */
  stepAppraisal(appraisal: Appraisal, rng: () => number): EndogenousState {
    const mid = (this.cfg.zMin + this.cfg.zMax) / 2
    const neutral: EndogenousState = { a: mid, v: mid, d: mid, n: mid, s: mid, c: mid, b: mid }
    this.z = stepState(this.z, appraisalToStimulus(appraisal), neutral, this.cfg, rng)
    return this.state
  }

  /**
   * Produce an immutable, content-addressed `StateSnapshot` (#3) of the current
   * endogenous state. Used to close the HAC/identity loop: snapshots are frozen and
   * fingerprinted so silent state drift is detectable (§25 #3).
   */
  snapshot(source: string, takenAt: number, agentId = '', userScope = ''): StateSnapshot {
    const fingerprint = stateSnapshotFingerprint(endogenousToSnapshotState(this.z), source, takenAt)
    return {
      id: `snap_${source}_${takenAt}_${fingerprint}`,
      schema: 'aijade.state_snapshot@1',
      agentId,
      userScope,
      takenAt,
      state: endogenousToSnapshotState(this.z),
      source,
      frozen: true,
      fingerprint,
    }
  }
}
