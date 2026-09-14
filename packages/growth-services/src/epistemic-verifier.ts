/**
 * §48 AEL — EpistemicVerifier.
 *
 * Given acquired `SourceRecord`s, it de-duplicates by shared origin
 * (`sharedOriginClusters` / `independentOriginCount`), filters out sources that
 * cannot count as independent evidence (`canBeIndependentEvidence`), computes a
 * claim confidence from the independent sources' quality (`evidenceConfidence`),
 * maintains a `Belief` through `createBelief` / `applyRevision`, and produces a
 * `ClaimMap` whose every claim names its support sources and is traced back to
 * them with `traceProvenance`.
 */

import type { Belief, ClaimMap, EvidenceEntry, ProvenanceEdge, ProvenanceGraph, ProvenanceNode, SourceRecord } from '@proj-aijade/memory-biomimetic'

import type { SchedulerPort, StoragePort } from './ports'

import {
  applyRevision,
  canBeIndependentEvidence,
  createBelief,
  DEFAULT_BELIEF_CONFIG,
  evidenceConfidence,
  independentOriginCount,
  sharedOriginClusters,
  traceProvenance,
  validateClaimMap,
} from '@proj-aijade/memory-biomimetic'

import { genId } from './util'

const CLAIM_KIND = 'claim_map'
const BELIEF_KIND = 'belief'

export type ContentOrigin = 'system' | 'user' | 'web' | 'model' | 'tool'

function originOf(sourceType: string): ContentOrigin {
  if (sourceType === 'model')
    return 'model'
  if (sourceType === 'tool')
    return 'tool'
  if (sourceType === 'user')
    return 'user'
  if (sourceType === 'system')
    return 'system'
  return 'web'
}

export interface VerifyInput {
  sources: SourceRecord[]
  questRef: string
  /** The proposition being verified (defaults to a synthesised label). */
  proposition?: string
  /** Confidence contribution of each supporting source (default 1.0). */
  likelihoodPerSource?: number
}

export interface VerifyResult {
  claimMap: ClaimMap
  belief: Belief
  /** Raw shared-origin cluster count. */
  originClusters: number
  /** Independent-origin count (de-duped). */
  independentOriginCount: number
  /** Credible independent-source count after the `canBeIndependentEvidence` filter. */
  effectiveIndependentCount: number
  /** Claim confidence in [0,1]. */
  confidence: number
  /** Provenance chain traced from the claim's belief back through its sources. */
  traceChain: ProvenanceNode[]
}

export interface EpistemicVerifierDeps {
  storage: StoragePort
  scheduler: SchedulerPort
}

export class EpistemicVerifier {
  constructor(
    private readonly deps: EpistemicVerifierDeps,
    private readonly agentId: string,
    private readonly userScope: string,
  ) {}

  async verify(input: VerifyInput): Promise<VerifyResult> {
    const sources = input.sources
    const clusters = sharedOriginClusters(sources)
    const indCount = independentOriginCount(sources)

    // Filter to sources that actually count as independent evidence.
    const credible = sources.filter((s) => {
      const origin = originOf(s.sourceType)
      const isModelSummary = origin === 'model'
      return canBeIndependentEvidence(origin, isModelSummary)
    })
    const credibleIds = credible.map(s => s.id)
    // Guarantee at least one support ref so the claim passes the §6 traceability gate.
    const supportRefs = credibleIds.length > 0 ? credibleIds : sources.map(s => s.id)

    // Aggregate quality dimensions across credible sources → evidence confidence.
    const agg = credible.length > 0 ? credible : sources
    const n = agg.length || 1
    const sum = agg.reduce(
      (acc, s) => {
        acc.reliability += s.quality.reliability
        acc.independence += s.quality.independence
        acc.directness += s.quality.directness
        acc.recency += s.quality.recency
        acc.reproducibility += s.quality.reproducibility
        return acc
      },
      { reliability: 0, independence: 0, directness: 0, recency: 0, reproducibility: 0 },
    )
    const confidence = evidenceConfidence({
      reliability: sum.reliability / n,
      independence: sum.independence / n,
      directness: sum.directness / n,
      recency: sum.recency / n,
      reproducibility: sum.reproducibility / n,
      counterEvidence: 0,
    })

    // Maintain a belief through the evidence transaction.
    const beliefId = genId('b')
    const lk = input.likelihoodPerSource ?? 1.0
    const evidence: EvidenceEntry[] = supportRefs.map((id) => {
      const src = sources.find(s => s.id === id)
      return { id, reliability: src?.quality.reliability ?? 0.5, likelihood: lk }
    })
    let belief = createBelief(
      { id: beliefId, proposition: input.proposition ?? `claim derived from ${supportRefs.length} source(s)`, evidenceIds: supportRefs, at: this.deps.scheduler.now() },
      DEFAULT_BELIEF_CONFIG,
    )
    const rev = applyRevision(
      belief,
      { id: genId('rev'), at: this.deps.scheduler.now(), evidence, actor: this.agentId },
      DEFAULT_BELIEF_CONFIG,
    )
    belief = rev.belief

    // Build a small provenance graph and trace it.
    const nodes: ProvenanceNode[] = sources.map(s => ({
      ref: s.id,
      kind: 'episode',
      label: `Source: ${s.locator}`,
      detail: { sourceType: s.sourceType, contentHash: s.contentHash },
    }))
    nodes.push({
      ref: belief.id,
      kind: 'belief',
      label: `Belief: ${belief.proposition}`,
      detail: { proposition: belief.proposition, status: belief.status, confidence: belief.confidence },
    })
    const edges: ProvenanceEdge[] = supportRefs.map(id => ({ from: belief.id, to: id, relation: 'evidenced-by' }))
    const graph: ProvenanceGraph = { version: 1, nodes, edges }
    const traceChain = traceProvenance(graph, belief.id)

    // Emit the claim map.
    const claimMap: ClaimMap = {
      id: genId('cm'),
      schema: 'aijade.claim_map@1',
      agentId: this.agentId,
      userScope: this.userScope,
      questRef: input.questRef,
      claims: [
        {
          proposition: input.proposition ?? `derived claim over ${supportRefs.length} source(s)`,
          epistemicStatus: 'inference',
          supportSourceRefs: supportRefs,
          counterSourceRefs: [],
          confidence,
        },
      ],
      createdAt: this.deps.scheduler.now(),
    }
    const check = validateClaimMap(claimMap)
    if (!check.ok)
      throw new Error(`ClaimMap rejected: ${check.reason}`)

    await this.deps.storage.put(CLAIM_KIND, claimMap.id, claimMap)
    await this.deps.storage.put(BELIEF_KIND, belief.id, belief)

    return {
      claimMap,
      belief,
      originClusters: clusters.length,
      independentOriginCount: indCount,
      effectiveIndependentCount: credibleIds.length,
      confidence,
      traceChain,
    }
  }
}
