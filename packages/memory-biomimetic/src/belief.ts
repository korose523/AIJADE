import type { BeliefConfig } from './types'

/**
 * DGM — Belief Graph (AIJADE v7 §10.2; data contract #5 `BeliefRevision` §25).
 *
 * The belief graph holds what the system is currently willing to *use*, separated
 * from the episodic evidence graph (which only holds what happened). Beliefs are
 * never written directly: every change goes through an **evidence transaction**
 *
 *     logit P(h|E) = logit P(h) + Σ_k r_k · ℓ_k
 *
 * where `r_k` is source reliability ∈ [0,1] and `ℓ_k` the evidence likelihood
 * contribution. Counter-evidence enters with a minus sign.
 *
 * Two hard rules from the spec:
 *  1. §6 — an entry with **no source must not enter the belief graph**
 *          (source traceability ≥ 99.5%).
 *  2. §10.2 — an LLM may *propose* `ℓ_k`, but a validator bounds it and records
 *          the rationale. So `r` and `ℓ` are clamped here, deterministically.
 *
 * Every function below is pure: same inputs ⇒ same outputs.
 */

export type BeliefStatus = 'hypothesis' | 'accepted' | 'contested' | 'retracted'

export type BeliefOwner = 'user' | 'agent' | 'world'

/** A source reference. `reliability` is clamped to [0,1] at use time. */
export interface BeliefSource {
  id: string
  reliability: number
}

/** One evidence item in a revision. `likelihood` may be LLM-proposed. */
export interface EvidenceEntry {
  id: string
  reliability: number
  likelihood: number
}

export interface Belief {
  id: string
  proposition: string
  scope: string
  /** sigmoid(logit) ∈ (0,1). */
  confidence: number
  /** Internal log-odds; the quantity the evidence transaction updates. */
  logit: number
  evidenceIds: string[]
  counterEvidenceIds: string[]
  validFrom: number
  validTo?: number
  status: BeliefStatus
  owner: BeliefOwner
  createdAt: number
  updatedAt: number
  /** Cumulative supporting logit magnitude (for the contested-ratio check). */
  supportLogit: number
  /** Cumulative counter logit magnitude. */
  counterLogit: number
}

/** v7 §25 contract #5 — an auditable belief update transaction. */
export interface BeliefRevision {
  id: string
  beliefId: string
  at: number
  evidenceIds: string[]
  counterEvidenceIds: string[]
  deltaLogit: number
  logitBefore: number
  logitAfter: number
  confidenceBefore: number
  confidenceAfter: number
  sourceReliabilities: number[]
  /** True when any r_k or ℓ_k was clamped by the validator. */
  clamped: boolean
  rationale: string
  actor: string
}

/** A candidate that was refused entry — recorded so traceability is measurable. */
export interface BeliefRejection {
  proposition: string
  reason: string
  at: number
  actor: string
}

export function clamp(x: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, x))
}

export function sigmoid(z: number): number {
  if (z >= 0) {
    const e = Math.exp(-z)
    return 1 / (1 + e)
  }
  const e = Math.exp(z)
  return e / (1 + e)
}

export function logit(p: number): number {
  const q = clamp(p, 1e-9, 1 - 1e-9)
  return Math.log(q / (1 - q))
}

/**
 * Compute Σ r_k·ℓ_k for supporting minus counter evidence, clamping each term.
 *
 * Returns the pieces needed for both the update and its audit record.
 */
export function revisionDelta(
  evidence: EvidenceEntry[],
  counterEvidence: EvidenceEntry[],
  cfg: BeliefConfig,
): {
  delta: number
  support: number
  counter: number
  reliabilities: number[]
  clamped: boolean
  rationale: string
} {
  const reliabilities: number[] = []
  const notes: string[] = []
  let clamped = false
  let support = 0
  let counter = 0

  // Supporting evidence contributes + r_k·ℓ_k. ℓ_k may in principle be negative
  // (a weakly disconfirming item filed under "supporting"), so it is clamped to
  // [−maxAbs, +maxAbs].
  for (const e of evidence) {
    const r = clamp(e.reliability, 0, 1)
    const l = clamp(e.likelihood, -cfg.maxAbsLikelihood, cfg.maxAbsLikelihood)
    if (r !== e.reliability || l !== e.likelihood) {
      clamped = true
      notes.push(`clamped ${e.id}: r=${e.reliability}->${r}, l=${e.likelihood}->${l}`)
    }
    reliabilities.push(r)
    support += r * l
  }

  // Counter-evidence enters with a minus sign (v7 §10.2: Σ r_k·ℓ_k with counter
  // subtracted). Its likelihood is a *magnitude* → clamped to [0, maxAbs] and
  // always subtracted, so a negative input can never flip into an addition.
  for (const e of counterEvidence) {
    const r = clamp(e.reliability, 0, 1)
    const l = clamp(e.likelihood, 0, cfg.maxAbsLikelihood)
    if (r !== e.reliability || l !== e.likelihood) {
      clamped = true
      notes.push(`clamped ${e.id}: r=${e.reliability}->${r}, l=${e.likelihood}->${l}`)
    }
    reliabilities.push(r)
    counter += r * l
  }

  const delta = support - counter

  return {
    delta,
    support,
    counter,
    reliabilities,
    clamped,
    rationale: notes.join('; '),
  }
}

/**
 * Derive the belief status from confidence and the support/counter balance.
 *
 * - `retracted`  : confidence at/below the retract threshold, or explicit retraction
 * - `contested`  : counter-evidence carries at least `contestedRatio` of the mass
 * - `accepted`   : confidence at/above the accept threshold and not contested
 * - `hypothesis` : everything else
 */
export function nextBeliefStatus(
  confidence: number,
  supportLogit: number,
  counterLogit: number,
  cfg: BeliefConfig,
): BeliefStatus {
  if (confidence <= cfg.retractThreshold)
    return 'retracted'
  const total = Math.abs(supportLogit) + Math.abs(counterLogit)
  const counterShare = total > 0 ? Math.abs(counterLogit) / total : 0
  if (counterShare >= cfg.contestedRatio)
    return 'contested'
  if (confidence >= cfg.acceptThreshold)
    return 'accepted'
  return 'hypothesis'
}

/** Create a new belief. Callers must have already verified a source exists. */
export function createBelief(
  input: {
    id: string
    proposition: string
    scope?: string
    owner?: BeliefOwner
    evidenceIds: string[]
    at: number
    validFrom?: number
    validTo?: number
  },
  cfg: BeliefConfig,
): Belief {
  const prior = clamp(cfg.priorConfidence, 1e-9, 1 - 1e-9)
  const z = logit(prior)
  return {
    id: input.id,
    proposition: input.proposition,
    scope: input.scope ?? 'global',
    confidence: prior,
    logit: z,
    evidenceIds: [...input.evidenceIds],
    counterEvidenceIds: [],
    validFrom: input.validFrom ?? input.at,
    validTo: input.validTo,
    status: nextBeliefStatus(prior, 0, 0, cfg),
    owner: input.owner ?? 'agent',
    createdAt: input.at,
    updatedAt: input.at,
    supportLogit: 0,
    counterLogit: 0,
  }
}

/** Apply one evidence transaction to a belief. Pure. */
export function applyRevision(
  belief: Belief,
  input: {
    id: string
    at: number
    evidence?: EvidenceEntry[]
    counterEvidence?: EvidenceEntry[]
    actor: string
    rationale?: string
  },
  cfg: BeliefConfig,
): { belief: Belief, revision: BeliefRevision } {
  const evidence = input.evidence ?? []
  const counterEvidence = input.counterEvidence ?? []
  const d = revisionDelta(evidence, counterEvidence, cfg)

  const logitBefore = belief.logit
  const logitAfter = logitBefore + d.delta
  const confidenceBefore = belief.confidence
  const confidenceAfter = clamp(sigmoid(logitAfter), 1e-9, 1 - 1e-9)
  const nextSupport = belief.supportLogit + d.support
  const nextCounter = belief.counterLogit + d.counter

  const next: Belief = {
    ...belief,
    logit: logitAfter,
    confidence: confidenceAfter,
    supportLogit: nextSupport,
    counterLogit: nextCounter,
    status: nextBeliefStatus(confidenceAfter, nextSupport, nextCounter, cfg),
    evidenceIds: [...belief.evidenceIds, ...evidence.map(e => e.id)],
    counterEvidenceIds: [...belief.counterEvidenceIds, ...counterEvidence.map(e => e.id)],
    updatedAt: input.at,
  }

  const revision: BeliefRevision = {
    id: input.id,
    beliefId: belief.id,
    at: input.at,
    evidenceIds: evidence.map(e => e.id),
    counterEvidenceIds: counterEvidence.map(e => e.id),
    deltaLogit: d.delta,
    logitBefore,
    logitAfter,
    confidenceBefore,
    confidenceAfter,
    sourceReliabilities: d.reliabilities,
    clamped: d.clamped,
    rationale: [input.rationale, d.rationale].filter(Boolean).join(' | '),
    actor: input.actor,
  }

  return { belief: next, revision }
}

/**
 * Explicit retraction (v7 §10.4 — never a silent overwrite).
 * Sets a validity end and records why; the original entry stays auditable.
 */
export function retract(
  belief: Belief,
  input: { id: string, at: number, actor: string, reason: string },
): { belief: Belief, revision: BeliefRevision } {
  const next: Belief = {
    ...belief,
    status: 'retracted',
    validTo: input.at,
    updatedAt: input.at,
  }
  const revision: BeliefRevision = {
    id: input.id,
    beliefId: belief.id,
    at: input.at,
    evidenceIds: [],
    counterEvidenceIds: [],
    deltaLogit: 0,
    logitBefore: belief.logit,
    logitAfter: belief.logit,
    confidenceBefore: belief.confidence,
    confidenceAfter: belief.confidence,
    sourceReliabilities: [],
    clamped: false,
    rationale: `retracted: ${input.reason}`,
    actor: input.actor,
  }
  return { belief: next, revision }
}
