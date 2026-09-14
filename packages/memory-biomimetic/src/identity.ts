/**
 * v7 §11 — Constrained Developmental Identity (CDI).
 *
 * ⚠️ SCOPE GUARD: this is the *identity* layer, NOT the hormone / presentation
 * layer (`PhysiologicalStateV3`) that already lives in `./types` + `./plasticity`.
 * §11.1 is explicit that the three identity layers are Constitutional / Character /
 * Expressive — a developmental-continuity model, not a mood vector. CDI must never
 * be wired to drive memory durability / salience either (that would re-trip the H2c
 * guard already enforced on HAC). Here identity is its own, independently testable
 * research-kernel module.
 *
 * Pipeline (§11.3):
 *   Evidence Window → IdentityCandidate → Constraint Solver → Shadow Evaluation
 *   → Drift Report → Auto/Manual Approval → Signed Identity Version.
 *
 * Everything is pure except the `IdentityController` wrapper, which holds mutable
 * state for a running agent. Signatures are deterministic so versions are auditable.
 */

import type { FeedbackEvent, StateSnapshot } from './contracts'

export type IdentityLayer = 'constitutional' | 'character' | 'expressive'

export const IDENTITY_LAYERS: readonly IdentityLayer[] = ['constitutional', 'character', 'expressive']

/** A point in identity-parameter space; each layer is a named numeric vector. */
export interface IdentityState {
  constitutional: Record<string, number>
  character: Record<string, number>
  expressive: Record<string, number>
}

export type IdentitySource = 'user' | 'agent' | 'world' | 'observation'

/** How the evidence was produced — a single user-emotion event may NOT drive identity. */
export type EvidenceTrigger = 'deliberate' | 'observation' | 'emotion'

export interface IdentityEvidence {
  /** The episode this evidence came from (used to prove cross-episode independence). */
  episodeId: string
  source: IdentitySource
  /** §6 traceability — a sourceless identity change is forbidden. */
  traceable: boolean
  kind: 'preference' | 'feedback' | 'boundary' | 'consent' | 'value' | 'observation'
  trigger: EvidenceTrigger
}

/** v7 §25 #6 — a proposed identity change, carrying its evidence. */
export interface IdentityCandidate {
  schema: 'aijade.identity_candidate@1'
  candidateId: string
  /** Who proposes. Constitutional layer is NOT model-writable (§11.1). */
  proposedBy: IdentitySource
  evidence: IdentityEvidence[]
  /** Proposed delta per layer; only the named keys change (added to current). */
  delta: Partial<IdentityState>
  /**
   * Required to touch the constitutional layer. Constitutional changes are "only
   * explicit upgrade" (§11.1) and a model may never initiate them.
   */
  explicitUpgrade?: boolean
  justification?: string
}

export interface CdiConfig {
  /** Max L2 norm of a single update step: ‖Δp‖₂ ≤ ε (§11.2). */
  epsilon: number
  /** Minimum number of distinct episodes the evidence must span (§11.2). */
  minIndependentEpisodes: number
  /** Hard safety bounds on constitutional params (C_safety). */
  safetyBounds: Record<string, { min: number, max: number }>
  /** Name of the consent parameter inside the constitutional layer. */
  consentParam: string
  /** Allowed range for the consent parameter (C_consent). */
  consentRange: [number, number]
}

export interface DriftReport {
  perLayer: Partial<Record<IdentityLayer, number>>
  total: number
  touchedLayers: IdentityLayer[]
  touchesConstitutional: boolean
}

export type SolveResult
  = | { ok: true, next: IdentityState, drift: DriftReport }
    | { ok: false, stage: 'validation' | 'constraint' | 'safety' | 'consent', reason: string, drift?: DriftReport }

export interface IdentityVersion {
  version: number
  /** Deterministic content signature (FNV-1a over canonical state). */
  signature: string
  parents: string[]
  params: IdentityState
  approvedBy: IdentitySource
  createdAt: number
  rolledBack: boolean
}

// ---------------------------------------------------------------------------
// defaults
// ---------------------------------------------------------------------------

export const DEFAULT_IDENTITY: IdentityState = {
  constitutional: { safetyBoundary: 0.5, userConsent: 0.5, harmThreshold: 0.5 },
  character: { verbosity: 0.5, formality: 0.5, curiosity: 0.5 },
  expressive: { warmth: 0.5, energy: 0.5 },
}

export const DEFAULT_CDI_CONFIG: CdiConfig = {
  epsilon: 0.5,
  minIndependentEpisodes: 2,
  safetyBounds: {
    safetyBoundary: { min: 0, max: 1 },
    userConsent: { min: 0, max: 1 },
    harmThreshold: { min: 0, max: 1 },
  },
  consentParam: 'userConsent',
  consentRange: [0, 1],
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function cloneState(s: IdentityState): IdentityState {
  return {
    constitutional: { ...s.constitutional },
    character: { ...s.character },
    expressive: { ...s.expressive },
  }
}

function canonical(o: unknown): string {
  if (o === null || typeof o !== 'object')
    return JSON.stringify(o)
  if (Array.isArray(o))
    return `[${o.map(canonical).join(',')}]`
  const obj = o as Record<string, unknown>
  const keys = Object.keys(obj).sort()
  return `{${keys.map(k => `${JSON.stringify(k)}:${canonical(obj[k])}`).join(',')}}`
}

/** Deterministic FNV-1a signature of an identity state (hex, zero-padded). */
export function identityHash(s: IdentityState): string {
  const str = canonical(s)
  let h = 0x811C9DC5
  for (let i = 0; i < str.length; i++) {
    h = (h ^ str.charCodeAt(i)) >>> 0
    h = (h * 0x01000193) >>> 0
  }
  return (h >>> 0).toString(16).padStart(8, '0')
}

export function l2Delta(delta: Partial<IdentityState>): number {
  let acc = 0
  for (const layer of IDENTITY_LAYERS) {
    const layerDelta = delta[layer]
    if (!layerDelta)
      continue
    for (const key of Object.keys(layerDelta))
      acc += layerDelta[key] * layerDelta[key]
  }
  return Math.sqrt(acc)
}

export function applyDelta(current: IdentityState, delta: Partial<IdentityState>): IdentityState {
  const next = cloneState(current)
  for (const layer of IDENTITY_LAYERS) {
    const layerDelta = delta[layer]
    if (!layerDelta)
      continue
    for (const key of Object.keys(layerDelta))
      next[layer][key] = (next[layer][key] ?? 0) + layerDelta[key]
  }
  return next
}

export function driftReport(_current: IdentityState, candidate: IdentityCandidate): DriftReport {
  const perLayer: Partial<Record<IdentityLayer, number>> = {}
  const touchedLayers: IdentityLayer[] = []
  for (const layer of IDENTITY_LAYERS) {
    const layerDelta = candidate.delta[layer]
    if (!layerDelta)
      continue
    let sum = 0
    for (const key of Object.keys(layerDelta))
      sum += layerDelta[key] * layerDelta[key]
    perLayer[layer] = Math.sqrt(sum)
    touchedLayers.push(layer)
  }
  let total = 0
  for (const layer of touchedLayers)
    total += perLayer[layer]! * perLayer[layer]!
  return {
    perLayer,
    total: Math.sqrt(total),
    touchedLayers,
    touchesConstitutional: touchedLayers.includes('constitutional'),
  }
}

// ---------------------------------------------------------------------------
// §25 closed-loop adapters — Feedback → CDI evidence/candidate, Snapshot → evidence
// ---------------------------------------------------------------------------

/**
 * Map a §25 `FeedbackEvent` (#14) onto `IdentityEvidence` for the CDI evidence
 * window (§11.2/§11.3). Explicit feedback (ratings, corrections, accept/decline)
 * becomes `kind: 'feedback'` from the user; implicit feedback (dwell, repeats)
 * becomes an `observation` from the world. Both are `traceable` by default and
 * carry their trigger, so a single emotion event can never silently drive identity
 * (the §11.2 guard still applies downstream in `validateIdentityCandidate`).
 */
export function feedbackToIdentityEvidence(
  feedback: FeedbackEvent,
  episodeId: string,
  traceable = true,
): IdentityEvidence {
  const explicit = feedback.type === 'explicit'
  return {
    episodeId,
    source: explicit ? 'user' : 'observation',
    traceable,
    kind: explicit ? 'feedback' : 'observation',
    trigger: explicit ? 'deliberate' : 'observation',
  }
}

/**
 * Build a small-step `IdentityCandidate` (#6) from a §25 `FeedbackEvent`, ready
 * for `solveIdentityUpdate`. The delta is a single-layer nudge so ‖Δp‖₂ ≤ ε is
 * preserved (§11.2). The caller supplies an episode id, the target layer/param, the
 * delta value, and who proposes it; `explicitUpgrade` is required for any
 * constitutional touch (enforced downstream by `validateIdentityCandidate`).
 */
export function feedbackToIdentityCandidate(
  feedback: FeedbackEvent,
  opts: {
    episodeId: string
    layer: IdentityLayer
    paramKey: string
    deltaValue: number
    proposedBy?: IdentitySource
    explicitUpgrade?: boolean
    justification?: string
    traceable?: boolean
  },
): IdentityCandidate {
  const evidence = feedbackToIdentityEvidence(feedback, opts.episodeId, opts.traceable ?? true)
  const inner = { [opts.paramKey]: opts.deltaValue }
  let delta: Partial<IdentityState> = {}
  switch (opts.layer) {
    case 'constitutional':
      delta = { constitutional: inner }
      break
    case 'character':
      delta = { character: inner }
      break
    case 'expressive':
      delta = { expressive: inner }
      break
  }
  return {
    schema: 'aijade.identity_candidate@1',
    candidateId: `fb_${feedback.id}`,
    proposedBy: opts.proposedBy ?? 'world',
    evidence: [evidence],
    delta,
    explicitUpgrade: opts.explicitUpgrade,
    justification: opts.justification,
  }
}

/**
 * Bridge a §25 `StateSnapshot` (#3) into the CDI evidence window (§11.3): the
 * frozen endogenous-state view becomes an `observation` from the world, so HAC's
 * closed-loop output can inform identity development without HAC ever driving
 * durability / salience (H2c guard preserved — this is evidence, not a write).
 */
export function snapshotToIdentityEvidence(
  _snapshot: StateSnapshot,
  episodeId: string,
  traceable = true,
): IdentityEvidence {
  return {
    episodeId,
    source: 'world',
    traceable,
    kind: 'observation',
    trigger: 'observation',
  }
}

// ---------------------------------------------------------------------------
// §11.2 validation — the §6 / §11.2 admissibility gate
// ---------------------------------------------------------------------------

export function validateIdentityCandidate(
  c: IdentityCandidate,
  cfg: CdiConfig,
): { ok: true } | { ok: false, reason: string } {
  if (c.evidence.length === 0)
    return { ok: false, reason: 'IdentityCandidate must carry evidence (v7 §6)' }

  if (c.evidence.some(e => !e.traceable))
    return { ok: false, reason: 'untraceable evidence forbidden (v7 §6)' }

  const episodes = new Set(c.evidence.map(e => e.episodeId))
  if (episodes.size < cfg.minIndependentEpisodes)
    return { ok: false, reason: `evidence must span ≥${cfg.minIndependentEpisodes} independent episodes` }

  if (c.evidence.every(e => e.trigger === 'emotion'))
    return { ok: false, reason: 'a single user-emotion event cannot drive identity change (§11.2)' }

  if (c.delta.constitutional && Object.keys(c.delta.constitutional).length > 0) {
    if (c.proposedBy === 'agent')
      return { ok: false, reason: 'constitutional layer is not model-writable (§11.1)' }
    if (!c.explicitUpgrade)
      return { ok: false, reason: 'constitutional change requires explicitUpgrade (§11.1)' }
  }

  return { ok: true }
}

function checkSafety(next: IdentityState, cfg: CdiConfig): { ok: true } | { ok: false, reason: string } {
  for (const key of Object.keys(cfg.safetyBounds)) {
    const val = next.constitutional[key]
    if (val === undefined)
      continue
    const { min, max } = cfg.safetyBounds[key]
    if (val < min || val > max)
      return { ok: false, reason: `safety bound violated on "${key}" (C_safety)` }
  }
  return { ok: true }
}

function checkConsent(next: IdentityState, cfg: CdiConfig): { ok: true } | { ok: false, reason: string } {
  const val = next.constitutional[cfg.consentParam]
  if (val === undefined)
    return { ok: true }
  const [lo, hi] = cfg.consentRange
  if (val < lo || val > hi)
    return { ok: false, reason: `consent out of range (C_consent)` }
  return { ok: true }
}

// ---------------------------------------------------------------------------
// §11.2 / §11.3 constraint solver (pure — never mutates `current`)
// ---------------------------------------------------------------------------

export function solveIdentityUpdate(
  current: IdentityState,
  candidate: IdentityCandidate,
  cfg: CdiConfig,
): SolveResult {
  const v = validateIdentityCandidate(candidate, cfg)
  if (!v.ok)
    return { ok: false, stage: 'validation', reason: v.reason }

  const drift = driftReport(current, candidate)
  if (drift.total > cfg.epsilon)
    return { ok: false, stage: 'constraint', reason: `drift bound violated (‖Δp‖=${drift.total.toFixed(3)} > ε=${cfg.epsilon})`, drift }

  const next = applyDelta(current, candidate.delta)
  const s = checkSafety(next, cfg)
  if (!s.ok)
    return { ok: false, stage: 'safety', reason: s.reason }

  const c = checkConsent(next, cfg)
  if (!c.ok)
    return { ok: false, stage: 'consent', reason: c.reason }

  return { ok: true, next, drift }
}

/** §11.2 "先在影子身份中评测" — evaluate without committing. Pure; `current` is untouched. */
export function evaluateShadow(
  current: IdentityState,
  candidate: IdentityCandidate,
  cfg: CdiConfig,
): SolveResult & { shadow: true } {
  return { ...solveIdentityUpdate(current, candidate, cfg), shadow: true }
}

// ---------------------------------------------------------------------------
// §40.2 identity metrics
// ---------------------------------------------------------------------------

/** Core Stability — 1 when the constitutional layer is untouched, falls with drift. */
export function coreStability(current: IdentityState, baseline: IdentityState): number {
  let d = 0
  for (const key of Object.keys(baseline.constitutional)) {
    const a = baseline.constitutional[key]
    const b = current.constitutional[key] ?? 0
    d += (a - b) * (a - b)
  }
  return Math.max(0, 1 - Math.sqrt(d))
}

/** Count of candidates rejected for exceeding the drift bound (Drift Bound Violations). */
export function countDriftViolations(results: SolveResult[]): number {
  return results.filter(r => !r.ok && r.stage === 'constraint').length
}

/** Recovery after rollback — 1 when current matches the rollback target, else degrades with distance. */
export function rollbackRecoveryRate(current: IdentityState, target: IdentityState): number {
  let d = 0
  for (const layer of IDENTITY_LAYERS) {
    for (const key of Object.keys(target[layer])) {
      const a = target[layer][key]
      const b = current[layer][key] ?? 0
      d += (a - b) * (a - b)
    }
  }
  return Math.max(0, 1 - Math.sqrt(d))
}

// ---------------------------------------------------------------------------
// controller wrapper (holds mutable state for a running agent)
// ---------------------------------------------------------------------------

export type ApplyResult
  = | { ok: true, version: IdentityVersion }
    | { ok: false, stage: string, reason: string }

export class IdentityController {
  private current: IdentityState
  private versions: IdentityVersion[] = []

  constructor(
    private readonly cfg: CdiConfig,
    initial?: IdentityState,
    private readonly clock: () => number = () => Date.now(),
    history?: IdentityVersion[],
  ) {
    this.current = initial ? cloneState(initial) : cloneState(DEFAULT_IDENTITY)
    if (history)
      this.versions = history.map(v => ({ ...v, params: cloneState(v.params) }))
  }

  get state(): IdentityState {
    return cloneState(this.current)
  }

  get history(): IdentityVersion[] {
    return this.versions.map(v => ({ ...v, params: cloneState(v.params) }))
  }

  /** Evaluate without committing (shadow path of §11.3). */
  shadow(candidate: IdentityCandidate): SolveResult {
    return solveIdentityUpdate(this.current, candidate, this.cfg)
  }

  /** Commit an accepted candidate → new signed version (append-only history). */
  apply(candidate: IdentityCandidate, approvedBy: IdentitySource = candidate.proposedBy): ApplyResult {
    const r = solveIdentityUpdate(this.current, candidate, this.cfg)
    if (!r.ok)
      return { ok: false, stage: r.stage, reason: r.reason }
    const version: IdentityVersion = {
      version: this.versions.length + 1,
      signature: identityHash(r.next),
      parents: this.versions.length ? [this.versions[this.versions.length - 1].signature] : [],
      params: r.next,
      approvedBy,
      createdAt: this.clock(),
      rolledBack: false,
    }
    this.versions.push(version)
    this.current = r.next
    return { ok: true, version }
  }

  /** Roll back to a prior signed version (restores its params, records a rollback version). */
  rollbackTo(signature: string, approvedBy: IdentitySource = 'user'): IdentityVersion {
    const target = this.versions.find(v => v.signature === signature)
    if (!target)
      throw new Error('unknown version signature')
    const version: IdentityVersion = {
      version: this.versions.length + 1,
      signature: identityHash(target.params),
      parents: [target.signature],
      params: cloneState(target.params),
      approvedBy,
      createdAt: this.clock(),
      rolledBack: true,
    }
    this.versions.push(version)
    this.current = cloneState(target.params)
    return version
  }
}
