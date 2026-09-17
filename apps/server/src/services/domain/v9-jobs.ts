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
