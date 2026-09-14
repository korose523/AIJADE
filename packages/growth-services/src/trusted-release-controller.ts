/**
 * §51 VSE — TrustedReleaseController.
 *
 * The promotion gate. It refuses to sign a release unless the proposal and
 * evidence pack both validate, `canPromote` passes (every evaluation gate green),
 * and a rollback path is available (the proposal carries a rollback plan). Only
 * then is a `SignedRelease` produced with a canary ratio ∈ [0,1] and a
 * `SigningPort` signature.
 */

import type { EvaluationEvidencePack, EvolutionProposal, SignedRelease } from '@proj-aijade/memory-biomimetic'

import type { SchedulerPort, SigningPort, StoragePort } from './ports'

import {
  canPromote,
  validateEvaluationEvidencePack,
  validateEvolutionProposal,
  validateSignedRelease,
} from '@proj-aijade/memory-biomimetic'

import { genId } from './util'

const KIND = 'signed_release'

export interface ReleaseInput {
  proposal: EvolutionProposal
  evidencePack: EvaluationEvidencePack
  approvedBy?: string
  /** Canary rollout fraction ∈ [0,1]; defaults to 0.1. */
  canaryRatio?: number
}

export interface ReleaseResult {
  ok: boolean
  reason?: string
  release?: SignedRelease
}

export interface TrustedReleaseControllerDeps {
  storage: StoragePort
  scheduler: SchedulerPort
  signing: SigningPort
}

export class TrustedReleaseController {
  constructor(
    private readonly deps: TrustedReleaseControllerDeps,
    private readonly agentId: string,
    _userScope: string,
  ) {}

  async release(input: ReleaseInput): Promise<ReleaseResult> {
    const pCheck = validateEvolutionProposal(input.proposal)
    if (!pCheck.ok)
      return { ok: false, reason: `proposal invalid: ${pCheck.reason}` }

    const eCheck = validateEvaluationEvidencePack(input.evidencePack)
    if (!eCheck.ok)
      return { ok: false, reason: `evidence pack invalid: ${eCheck.reason}` }

    const promote = canPromote(input.evidencePack)
    if (!promote.ok)
      return { ok: false, reason: `promotion blocked: ${promote.reason}` }

    // Rollback availability is implied by the proposal carrying a rollback plan.
    const rollbackAvailable = !!input.proposal.rollbackPlan && input.proposal.rollbackPlan.trim().length > 0
    if (!rollbackAvailable)
      return { ok: false, reason: 'rollback plan required for a trusted release' }

    const canaryRatio = Math.min(1, Math.max(0, input.canaryRatio ?? 0.1))
    const version = `${input.proposal.baselineVersion}-rc-${genId('v')}`

    const release: SignedRelease = {
      id: genId('sr'),
      schema: 'aijade.signed_release@1',
      version,
      proposalRef: input.proposal.id,
      evidencePackRef: input.evidencePack.id,
      approvedBy: input.approvedBy ?? this.agentId,
      signedAt: this.deps.scheduler.now(),
      signature: '',
      canaryRatio,
      rollbackAvailable: true,
    }
    release.signature = this.deps.signing.sign({
      proposalRef: release.proposalRef,
      evidencePackRef: release.evidencePackRef,
      version: release.version,
      canaryRatio: release.canaryRatio,
      rollbackAvailable: release.rollbackAvailable,
    })

    const check = validateSignedRelease(release)
    if (!check.ok)
      return { ok: false, reason: `signed release invalid: ${check.reason}` }
    await this.deps.storage.put(KIND, release.id, release)
    return { ok: true, release }
  }
}
