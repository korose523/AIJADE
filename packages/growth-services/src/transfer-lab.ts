/**
 * §49.3 — TransferLab.
 *
 * Produces a `TransferRecord` from a source → target domain, optionally informed by
 * an `AssociationPath` or a prior `TransferRecord`. Tier inference: when a
 * validated path / prior transfer is present we emit a T2+ transfer and set
 * `validated = true` (required by `validateTransferRecord` for T2+); otherwise a
 * T0/T1 transfer with `validated = false`. `negativeTransferSignal` defaults to 0.
 */

import type { AssociationPath, TransferRecord } from '@proj-aijade/memory-biomimetic'

import type { SchedulerPort, StoragePort } from './ports'

import { validateTransferRecord } from '@proj-aijade/memory-biomimetic'

import { genId } from './util'

const KIND = 'transfer_record'

export interface ProposeTransferInput {
  sourceDomain: string
  targetDomain: string
  /** A reasoning path that produced this transfer (the "why" path). */
  path?: AssociationPath
  /** A prior transfer to carry validation forward from. */
  priorTransfer?: TransferRecord
  /** Explicit validated override (defaults to priorTransfer.validated). */
  validated?: boolean
  invariantsPreserved?: string[]
  brokenConditions?: string[]
  predictedOutcome?: string
  measuredOutcome?: string
  /** Negative-transfer signal ∈ [0,1]; defaults to 0. */
  negativeTransferSignal?: number
}

export interface TransferLabDeps {
  storage: StoragePort
  scheduler: SchedulerPort
}

export class TransferLab {
  constructor(
    private readonly deps: TransferLabDeps,
    private readonly agentId: string,
    private readonly userScope: string,
  ) {}

  async propose(input: ProposeTransferInput): Promise<TransferRecord> {
    const validated = input.validated ?? (input.priorTransfer?.validated ?? false)
    // T2+ must be validated (v8 §49.3); otherwise a T0/T1 transfer.
    const tier: TransferRecord['tier'] = validated ? 'T2' : 'T1'

    const record: TransferRecord = {
      id: genId('tr'),
      schema: 'aijade.transfer_record@1',
      agentId: this.agentId,
      userScope: this.userScope,
      sourceDomain: input.sourceDomain,
      targetDomain: input.targetDomain,
      invariantsPreserved: input.invariantsPreserved ?? [],
      brokenConditions: input.brokenConditions ?? [],
      predictedOutcome: input.predictedOutcome ?? 'pending',
      measuredOutcome: input.measuredOutcome ?? 'pending',
      negativeTransferSignal: input.negativeTransferSignal ?? 0,
      tier,
      validated,
      createdAt: this.deps.scheduler.now(),
    }
    const check = validateTransferRecord(record)
    if (!check.ok)
      throw new Error(`TransferRecord rejected: ${check.reason}`)
    await this.deps.storage.put(KIND, record.id, record)
    return record
  }

  async get(id: string): Promise<TransferRecord | undefined> {
    return this.deps.storage.get<TransferRecord>(KIND, id)
  }
}
