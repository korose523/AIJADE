/**
 * §48.6 — SynthesisWorkbench.
 *
 * Given a quest, its acquired `SourceRecord`s and a synthesised payload, it emits a
 * `KnowledgeArtifact`: it derives the contract's `sources` from the source records
 * (mandatory §6 traceability), computes an evidence-graph reference that encodes
 * the de-duplicated independent-origin count (`independentOriginCount`), and
 * validates the artefact.
 */

import type { ContractSource, KnowledgeArtifact, SourceRecord } from '@proj-aijade/memory-biomimetic'

import type { SchedulerPort, StoragePort } from './ports'

import { independentOriginCount, validateKnowledgeArtifact } from '@proj-aijade/memory-biomimetic'

import { genId } from './util'

const KIND = 'knowledge_artifact'

export type ArtifactKind = KnowledgeArtifact['kind']

export interface SynthesizeInput {
  questRef: string
  kind: ArtifactKind
  payload: unknown
  /** The source records backing the artefact (must be ≥1 for §6 traceability). */
  sourceRecords: SourceRecord[]
  /** Optionally override the `trusted` flag per sourceType. */
  trustedTypes?: string[]
}

export interface SynthesisWorkbenchDeps {
  storage: StoragePort
  scheduler: SchedulerPort
}

export class SynthesisWorkbench {
  constructor(
    private readonly deps: SynthesisWorkbenchDeps,
    private readonly agentId: string,
    private readonly userScope: string,
  ) {}

  async synthesize(input: SynthesizeInput): Promise<KnowledgeArtifact> {
    if (input.sourceRecords.length === 0)
      throw new Error('KnowledgeArtifact requires ≥1 source (v7 §6)')

    const trusted = new Set(input.trustedTypes ?? [])
    const sources: ContractSource[] = input.sourceRecords.map(s => ({
      ref: s.id,
      trusted: trusted.has(s.sourceType),
    }))
    const indep = independentOriginCount(input.sourceRecords)
    const evidenceGraphRef = `evg:indep=${indep}:${input.sourceRecords.map(s => s.id).join(',')}`

    const artifact: KnowledgeArtifact = {
      id: genId('ka'),
      schema: 'aijade.knowledge_artifact@1',
      agentId: this.agentId,
      userScope: this.userScope,
      kind: input.kind,
      questRef: input.questRef,
      payload: input.payload,
      evidenceGraphRef,
      sources,
      createdAt: this.deps.scheduler.now(),
    }
    const check = validateKnowledgeArtifact(artifact)
    if (!check.ok)
      throw new Error(`KnowledgeArtifact rejected: ${check.reason}`)
    await this.deps.storage.put(KIND, artifact.id, artifact)
    return artifact
  }

  async get(id: string): Promise<KnowledgeArtifact | undefined> {
    return this.deps.storage.get<KnowledgeArtifact>(KIND, id)
  }
}
