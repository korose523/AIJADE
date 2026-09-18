import type {
  CandidateVersion,
  EvaluationEvidencePack,
  PgcState4,
  ShadowParamsProposal,
  V9VideoObservationInput,
} from '@proj-aijade/memory-biomimetic'
import type Redis from 'ioredis'

export const V9_PERCEPTION_QUEUE = 'aijade:v9:perception'

/**
 * Worker dead-letter keys.
 *
 * These used to be inline string literals in `bin/worker.ts`, which meant the key
 * a failed job is actually parked under was not assertable by any test or
 * acceptance script — a verifier could "prove" the dead-letter path while the
 * worker wrote to a different key. They live here so the worker and everything
 * that verifies it read one source.
 *
 * (`V9_MEMORY_DEAD_LETTER` belongs to the memory queue, not the v9 ones, but it is
 * declared alongside the others for that same single-source reason.)
 */
export const V9_PERCEPTION_DEAD_LETTER = 'aijade:v9:dead-letter'
export const V9_PROMOTION_DEAD_LETTER = 'aijade:v9:promotion:dead-letter'
export const V9_MEMORY_DEAD_LETTER = 'aijade:memory:dead-letter'

/**
 * 队列 BRPOP 阻塞超时（秒）。
 *
 * worker 对 4 条队列**串行轮询**（单循环内 Promise.all 并发发起，但一轮结束才进下一轮），
 * 空转一轮耗时 ≈ 本超时。E2E 实测：5s 超时下"观察 → 学习提案"端到端时延最坏 ~15s
 * （提案落在轮询周期的空档需等下一轮）；收紧为 1s 后时延最坏 ~1s，空轮询的 Redis
 * 压力（4 req/s）仍可忽略。不要为"减少空轮询"放大此值 —— 它直接决定异步派发的
 * 尾时延上界。
 */
export const V9_DEQUEUE_BLOCK_SECONDS = 1

/** Park a failed job for operator inspection. The worker and its verifiers share this. */
export async function parkDeadLetter(
  redis: Redis,
  key: string,
  entry: { job: unknown, error: string },
): Promise<void> {
  await redis.lpush(key, JSON.stringify(entry))
}

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
  const result = await redis.brpop(V9_PERCEPTION_QUEUE, V9_DEQUEUE_BLOCK_SECONDS)
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
  const result = await redis.brpop(V9_PROMOTION_QUEUE, V9_DEQUEUE_BLOCK_SECONDS)
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

// ---------------------------------------------------------------------------
// Video observation queue (A 路: webpage_text / video_transcript -> evidence)
// ---------------------------------------------------------------------------

export const V9_VIDEO_OBSERVATION_QUEUE = 'aijade:v9:video-observation'
export const V9_VIDEO_OBSERVATION_DEAD_LETTER = 'aijade:v9:video-observation:dead-letter'

export interface V9VideoObservationJob {
  jobId: string
  input: V9VideoObservationInput
}

export async function enqueueV9VideoObservation(redis: Redis, job: V9VideoObservationJob): Promise<void> {
  await redis.lpush(V9_VIDEO_OBSERVATION_QUEUE, JSON.stringify(job))
}

export async function dequeueV9VideoObservation(redis: Redis): Promise<V9VideoObservationJob | undefined> {
  const result = await redis.brpop(V9_VIDEO_OBSERVATION_QUEUE, V9_DEQUEUE_BLOCK_SECONDS)
  if (!result)
    return undefined
  const [, raw] = result
  const parsed: unknown = JSON.parse(raw)
  if (!parsed || typeof parsed !== 'object' || !('jobId' in parsed) || !('input' in parsed))
    throw new Error('invalid v9 video-observation job payload')
  return parsed as V9VideoObservationJob
}
