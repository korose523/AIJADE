import type { EvaluationEvidencePack } from './contracts-v8'

/**
 * v8 §51 — VSE: Verified Self-Evolution.
 *
 * VSE lets the system improve its own strategies, workflows, skills and
 * non-critical code — but never by directly rewriting the trusted core. Changes
 * only happen through proposals, sandboxes, evaluation, signed release and
 * rollback. The E0–E5 grading (§51.1) is the hard boundary: the agent may
 * optimise E1–E3, must defer E4 to human review, and can never touch E5 (the
 * safety constitution, keys, audit and release root). That boundary is part of
 * trustworthy growth, not a capability gap.
 *
 * Pure and deterministic; the release controller / runtime wiring lives in the
 * store / config layer.
 */

// ---------------------------------------------------------------------------
// §51.1 — evolution object grading
// ---------------------------------------------------------------------------

export type EvolutionGrade = 'E0' | 'E1' | 'E2' | 'E3' | 'E4' | 'E5'

/** What level of automation is permitted for a grade. */
export type AutomationLevel
  = | 'auto' // E0 — automatic, short-lived
    | 'auto_propose_offline_eval' // E1 — auto-propose, enable after offline eval
    | 'sandbox_sign_gray' // E2 — sandbox test, sign, canary
    | 'full_test_review' // E3 — full test + review/pre-authorisation, then release
    | 'human_review_required' // E4 — no autonomous modification; human review
    | 'forbidden' // E5 — never modifiable by the agent

/** §51.1 — the automation ceiling for each grade. */
export function automationAllowed(grade: EvolutionGrade): AutomationLevel {
  switch (grade) {
    case 'E0': return 'auto'
    case 'E1': return 'auto_propose_offline_eval'
    case 'E2': return 'sandbox_sign_gray'
    case 'E3': return 'full_test_review'
    case 'E4': return 'human_review_required'
    case 'E5': return 'forbidden'
  }
}

/**
 * §51.1 — whether the agent may autonomously propose/apply a change to an object
 * of this grade. E4 and E5 are off-limits for autonomous modification.
 */
export function assertEvolvable(grade: EvolutionGrade): { ok: true } | { ok: false, reason: string } {
  if (grade === 'E5')
    return { ok: false, reason: 'E5 (safety constitution / keys / audit / release root) can never be modified by the agent (v8 §51.1)' }
  if (grade === 'E4')
    return { ok: false, reason: 'E4 (core orchestration / memory transactions / identity constraints / permissions) requires human review; no autonomous direct modification (v8 §51.1)' }
  return { ok: true }
}

// ---------------------------------------------------------------------------
// §51.3 — self-evolution pipeline
// ---------------------------------------------------------------------------

export const EVOLUTION_PIPELINE = [
  'CAPABILITY_GAP',
  'REPRODUCIBLE_ISSUE',
  'ROOT_CAUSE_HYPOTHESES',
  'CHANGE_SPECIFICATION',
  'CANDIDATE_PATCH',
  'STATIC_ANALYSIS',
  'DEPENDENCY_LICENSE_SCAN',
  'UNIT_CONTRACT_PROPERTY_TESTS',
  'SECURITY_SANDBOX',
  'HISTORICAL_REPLAY',
  'ADVERSARIAL_EVALUATION',
  'BENCHMARK_COMPARISON',
  'SHADOW_MODE',
  'CANARY_RELEASE',
  'SIGNED_PROMOTION',
  'RUNTIME_MONITORING',
] as const

export type EvolutionPipelineStage = typeof EVOLUTION_PIPELINE[number]
export type EvolutionStage = EvolutionPipelineStage | 'KEPT' | 'ROLLED_BACK'

export type EvolutionEvent = 'advance' | 'keep' | 'rollback'

/**
 * §51.3 — pipeline state machine. `advance` moves forward; from RUNTIME_MONITORING,
 * `keep` commits the release (terminal KEPT) and `rollback` triggers automatic
 * rollback (terminal ROLLED_BACK). Illegal events return null.
 */
export function nextEvolutionStage(current: EvolutionStage, event: EvolutionEvent): EvolutionStage | null {
  if (current === 'KEPT' || current === 'ROLLED_BACK')
    return null
  if (event === 'rollback')
    return 'ROLLED_BACK'
  if (event === 'keep')
    return current === 'RUNTIME_MONITORING' ? 'KEPT' : null
  // advance
  const idx = EVOLUTION_PIPELINE.indexOf(current as EvolutionPipelineStage)
  if (idx === -1 || idx === EVOLUTION_PIPELINE.length - 1)
    return null
  return EVOLUTION_PIPELINE[idx + 1]
}

// ---------------------------------------------------------------------------
// §51.3 — promotion gate over the evaluation evidence pack
// ---------------------------------------------------------------------------

/**
 * §51.3 — a candidate may only be promoted if every evaluation gate in its
 * evidence pack passes. The core unit/contract/property-test gate is mandatory;
 * optional stages, when present, must also pass. Returns a refusal reason so the
 * release controller can record why a promotion was blocked.
 */
export function canPromote(pack: EvaluationEvidencePack): { ok: true } | { ok: false, reason: string } {
  if (!pack.unitContractPropertyTests.passed)
    return { ok: false, reason: 'core unit/contract/property tests did not pass' }
  if (pack.staticAnalysis && !pack.staticAnalysis.passed)
    return { ok: false, reason: 'static analysis failed' }
  if (pack.dependencyLicenseScan && !pack.dependencyLicenseScan.passed)
    return { ok: false, reason: 'dependency/license scan failed' }
  if (pack.securitySandbox && !pack.securitySandbox.passed)
    return { ok: false, reason: 'security sandbox reported escapes' }
  if (pack.historicalReplay && !pack.historicalReplay.passed)
    return { ok: false, reason: 'historical replay showed regressions' }
  if (pack.adversarialEval && !pack.adversarialEval.passed)
    return { ok: false, reason: 'adversarial evaluation found issues' }
  return { ok: true }
}

// ---------------------------------------------------------------------------
// §51.4 — candidate version selection (constraint optimisation)
// ---------------------------------------------------------------------------

export interface CandidateVersion {
  id: string
  /** ΔQuality: improvement over baseline (higher is better). */
  deltaQuality: number
  deltaLatency: number
  deltaCost: number
  risk: number
  complexity: number
  drift: number
  /** Absolute safety level of the candidate. */
  safety: number
  /** Absolute safety level of the baseline. */
  baselineSafety: number
  coreInvariantsHold: boolean
  rollbackAvailable: boolean
}

export interface EvolutionWeights {
  alphaLatency: number
  betaCost: number
  gammaRisk: number
  etaComplexity: number
  kappaDrift: number
}

export const DEFAULT_EVOLUTION_WEIGHTS: EvolutionWeights = {
  alphaLatency: 1,
  betaCost: 1,
  gammaRisk: 2,
  etaComplexity: 0.5,
  kappaDrift: 1.5,
}

/** §51.4 — objective: ΔQuality − αΔLatency − βΔCost − γRisk − ηComplexity − κDrift. */
export function evolutionObjective(c: CandidateVersion, w: EvolutionWeights = DEFAULT_EVOLUTION_WEIGHTS): number {
  return c.deltaQuality
    - w.alphaLatency * c.deltaLatency
    - w.betaCost * c.deltaCost
    - w.gammaRisk * c.risk
    - w.etaComplexity * c.complexity
    - w.kappaDrift * c.drift
}

/** §51.4 — hard constraints: Safety(v') ≥ Safety(v) ∧ CoreInvariants ∧ Rollback. */
export function satisfiesEvolutionConstraints(c: CandidateVersion): boolean {
  return c.safety >= c.baselineSafety && c.coreInvariantsHold && c.rollbackAvailable
}

/**
 * §51.4 — choose the best candidate version under the hard constraints. Candidates
 * that reduce safety, break core invariants, or lack a rollback path are filtered
 * out first; among the rest, the highest objective wins. Returns null if no
 * candidate is feasible (so the system keeps the baseline rather than forcing a
 * bad change).
 */
export function selectCandidateVersion(
  candidates: CandidateVersion[],
  w: EvolutionWeights = DEFAULT_EVOLUTION_WEIGHTS,
): CandidateVersion | null {
  let best: CandidateVersion | null = null
  let bestScore = -Infinity
  for (const c of candidates) {
    if (!satisfiesEvolutionConstraints(c))
      continue
    const score = evolutionObjective(c, w)
    if (score > bestScore) {
      bestScore = score
      best = c
    }
  }
  return best
}
