import type {
  CandidateVersion,
  EvaluationEvidencePack,
  PgcState4,
  ShadowParamsProposal,
} from '@proj-aijade/memory-biomimetic'
import type Redis from 'ioredis'

export const V9_PERCEPTION_QUEUE = 'aijade:v9:perception'

export interface V9PerceptionJob {
  jobId: string
  input: {
    eventId: string
    sessionId: string
    traceId: string
    correlationId: string
    timestamp: number
    originDevice: string
    privacyLevel: 0 | 1 | 2 | 3
    riskScore: number
    source: string
    content: string
  }
}

export async function enqueueV9Perception(redis: Redis, job: V9PerceptionJob): Promise<void> {
  await redis.lpush(V9_PERCEPTION_QUEUE, JSON.stringify(job))
}

export async function dequeueV9Perception(redis: Redis): Promise<V9PerceptionJob | undefined> {
  const result = await redis.brpop(V9_PERCEPTION_QUEUE, 5)
  if (!result)
    return undefined
  const [, raw] = result
  const parsed: unknown = JSON.parse(raw)
  if (!parsed || typeof parsed !== 'object' || !('jobId' in parsed) || !('input' in parsed))
    throw new Error('invalid v9 perception job payload')
  return parsed as V9PerceptionJob
}

// ---------------------------------------------------------------------------
// Shadow-param promotion queue (v10 §3 — gated behind EvidenceGate + PGC verdict)
// ---------------------------------------------------------------------------

export const V9_PROMOTION_QUEUE = 'aijade:v9:promotion'

export interface V9PromotionJob {
  jobId: string
  input: {
    proposalId: string
    sessionId: string
    traceId: string
    tick: number
    inputHash: string
    /** The evaluation evidence pack that the EvidenceGate evaluates via `canPromote`. */
    evaluationPack: EvaluationEvidencePack
    /** The reduced shadow-params proposal mapped to a PGC candidate write. */
    proposal: ShadowParamsProposal
    /** Optional candidate version (v8 §51.4), carried for selection metadata. */
    candidateVersion?: CandidateVersion
    /** Optional PGC v6 endogenous state s_t; the PGC write gate requires commit_possible === true when present. */
    pgcV6State?: PgcState4
  }
}

export async function enqueueV9Promotion(redis: Redis, job: V9PromotionJob): Promise<void> {
  await redis.lpush(V9_PROMOTION_QUEUE, JSON.stringify(job))
}

export async function dequeueV9Promotion(redis: Redis): Promise<V9PromotionJob | undefined> {
  const result = await redis.brpop(V9_PROMOTION_QUEUE, 5)
  if (!result)
    return undefined
  const [, raw] = result
  const parsed: unknown = JSON.parse(raw)
  if (
    !parsed
    || typeof parsed !== 'object'
    || !('jobId' in parsed)
    || !('input' in parsed)
  ) {
    throw new Error('invalid v9 promotion job payload')
  }
  const input = (parsed as { input: unknown }).input
  const inObj = input as Record<string, unknown>
  if (
    !input
    || typeof input !== 'object'
    || typeof inObj.proposalId !== 'string'
    || typeof inObj.sessionId !== 'string'
    || typeof inObj.traceId !== 'string'
    || typeof inObj.tick !== 'number'
    || typeof inObj.inputHash !== 'string'
    || typeof inObj.evaluationPack !== 'object'
    || inObj.evaluationPack === null
    || typeof inObj.proposal !== 'object'
    || inObj.proposal === null
  ) {
    throw new Error('invalid v9 promotion job payload')
  }
  const pack = inObj.evaluationPack as Record<string, unknown>
  if (typeof pack.unitContractPropertyTests !== 'object' || pack.unitContractPropertyTests === null) {
    throw new Error('invalid v9 promotion job payload: missing unitContractPropertyTests')
  }
  return parsed as V9PromotionJob
}
