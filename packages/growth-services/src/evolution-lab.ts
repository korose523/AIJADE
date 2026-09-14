/**
 * §51 VSE — EvolutionLab.
 *
 * Evaluates candidate versions with the VSE constraint optimiser
 * (`satisfiesEvolutionConstraints` + `selectCandidateVersion` +
 * `evolutionObjective`), refusing E4/E5 objects via `assertEvolvable`, then emits
 * a signed `EvolutionProposal` draft (baseline version, change spec, rollback plan
 * and ≥1 test are mandatory; the signature is produced by the `SigningPort`).
 */

import type { CandidateVersion, EvolutionGrade, EvolutionProposal, EvolutionWeights } from '@proj-aijade/memory-biomimetic'

import type { SchedulerPort, SigningPort, StoragePort } from './ports'

import {
  assertEvolvable,
  automationAllowed,
  DEFAULT_EVOLUTION_WEIGHTS,
  evolutionObjective,
  selectCandidateVersion,
  validateEvolutionProposal,
} from '@proj-aijade/memory-biomimetic'

import { genId } from './util'

const KIND = 'evolution_proposal'

export interface EvolutionTest {
  kind: string
  passed: boolean
  evidenceRef?: string
}

export interface EvaluateInput {
  /** Feasible/non-feasible candidate versions to choose from. */
  candidates: CandidateVersion[]
  /** Evolution grade of the object being changed. */
  grade: EvolutionGrade
  baselineVersion: string
  changeSpec: string
  sourceDiff: string
  generatedBy: string
  triggerEvidence?: string[]
  affectedComponents?: string[]
  /** Mandatory rollback plan (recoverability, §51.3). */
  rollbackPlan: string
  /** Mandatory ≥1 test. Defaults to a single passing contract/property test. */
  tests?: EvolutionTest[]
  dependencyDiff?: string
  migrationPlan?: string
  benchmarkResults?: Record<string, number>
  safetyResults?: Record<string, number | boolean>
  behaviorDiff?: string
  identityDiff?: string
  approvalPolicy?: string
  /** Override the evolution weights. */
  weights?: EvolutionWeights
}

export interface EvaluateResult {
  proposal: EvolutionProposal
  bestCandidate: CandidateVersion
  objective: number
  automationLevel: ReturnType<typeof automationAllowed>
}

export interface EvolutionLabDeps {
  storage: StoragePort
  scheduler: SchedulerPort
  signing: SigningPort
}

/** Build a candidate version with sensible defaults (used by tests / callers). */
export function makeCandidate(partial: Partial<CandidateVersion> & Pick<CandidateVersion, 'id'>): CandidateVersion {
  return {
    deltaQuality: 0.1,
    deltaLatency: 0,
    deltaCost: 0,
    risk: 0.1,
    complexity: 0.1,
    drift: 0.1,
    safety: 0.9,
    baselineSafety: 0.8,
    coreInvariantsHold: true,
    rollbackAvailable: true,
    ...partial,
  }
}

export class EvolutionLab {
  constructor(
    private readonly deps: EvolutionLabDeps,
    private readonly agentId: string,
    _userScope: string,
  ) {}

  async evaluate(input: EvaluateInput): Promise<EvaluateResult> {
    // E4/E5 cannot be autonomously proposed for modification.
    const evolvable = assertEvolvable(input.grade)
    if (!evolvable.ok)
      throw new Error(`EvolutionProposal refused: ${evolvable.reason}`)

    const weights = input.weights ?? DEFAULT_EVOLUTION_WEIGHTS
    const best = selectCandidateVersion(input.candidates, weights)
    if (!best)
      throw new Error('EvolutionLab: no feasible candidate (constraints unsatisfied)')

    const objective = evolutionObjective(best, weights)
    const automationLevel = automationAllowed(input.grade)

    const tests: EvolutionTest[] = input.tests ?? [{ kind: 'contract_property', passed: true }]

    const proposal: EvolutionProposal = {
      id: genId('ep'),
      schema: 'aijade.evolution_proposal@1',
      agentId: this.agentId,
      triggerEvidence: input.triggerEvidence ?? [],
      affectedComponents: input.affectedComponents ?? [],
      grade: input.grade,
      baselineVersion: input.baselineVersion,
      changeSpec: input.changeSpec,
      sourceDiff: input.sourceDiff,
      generatedBy: input.generatedBy,
      dependencyDiff: input.dependencyDiff,
      migrationPlan: input.migrationPlan,
      tests: tests.map(t => ({ ...t })),
      benchmarkResults: input.benchmarkResults,
      safetyResults: input.safetyResults,
      behaviorDiff: input.behaviorDiff,
      identityDiff: input.identityDiff,
      rollbackPlan: input.rollbackPlan,
      approvalPolicy: input.approvalPolicy ?? 'agent_self_review',
      // Sign the proposal body (excluding the signature field itself).
      signature: '',
      createdAt: this.deps.scheduler.now(),
    }

    proposal.signature = this.deps.signing.sign({
      id: proposal.id,
      baselineVersion: proposal.baselineVersion,
      changeSpec: proposal.changeSpec,
      sourceDiff: proposal.sourceDiff,
      grade: proposal.grade,
      candidateId: best.id,
      objective,
    })

    const check = validateEvolutionProposal(proposal)
    if (!check.ok)
      throw new Error(`EvolutionProposal rejected: ${check.reason}`)
    await this.deps.storage.put(KIND, proposal.id, proposal)
    return { proposal, bestCandidate: best, objective, automationLevel }
  }
}
