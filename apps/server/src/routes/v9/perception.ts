import type { V9CausalRuntime } from '@proj-aijade/memory-biomimetic'
import type Redis from 'ioredis'

import type { HonoEnv } from '../../types/hono'

import { Hono } from 'hono'
import { safeParse } from 'valibot'

import { authGuard } from '../../middlewares/auth'
import { enqueueV9Perception } from '../../services/domain/v9-jobs'
import { createBadRequestError } from '../../utils/error'
import { nanoid } from '../../utils/id'
import { v9PerceptionSchema } from './schema'

export function createV9PerceptionRoutes(runtime: V9CausalRuntime, redis?: Redis) {
  return new Hono<HonoEnv>()
    .use('*', authGuard)
    .post('/', async (c) => {
      const result = safeParse(v9PerceptionSchema, await c.req.json())
      if (!result.success)
        throw createBadRequestError('Invalid v9 perception input', 'INVALID_V9_PERCEPTION', result.issues)

      const input = {
        eventId: result.output.event_id,
        sessionId: result.output.session_id,
        traceId: result.output.trace_id,
        correlationId: result.output.correlation_id,
        timestamp: result.output.timestamp,
        originDevice: result.output.origin_device,
        privacyLevel: result.output.privacy_level,
        riskScore: result.output.risk_score,
        source: result.output.source,
        content: result.output.content,
        stimulusFeatures: result.output.stimulus_features,
        riskLevel: result.output.risk_level,
      }
      if (redis) {
        await enqueueV9Perception(redis, { jobId: nanoid(), input })
        return c.json({ ok: true, queued: true }, 202)
      }
      const processed = await runtime.processPerception(input)
      return c.json({
        ok: true,
        txId: processed.tx.tx_id,
        status: processed.tx.status,
        committedCount: processed.tx.committed.length,
        rejectedCount: processed.tx.rejected.length,
        throttledCount: processed.tx.throttled.length,
      }, 201)
    })
}
