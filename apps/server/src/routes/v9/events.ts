import type { AijadeEvent, V9CausalRuntime, V9VideoObservationInput } from '@proj-aijade/memory-biomimetic'
import type Redis from 'ioredis'

import type { V9EventService } from '../../services/domain/v9-events'
import type { HonoEnv } from '../../types/hono'

import { Hono } from 'hono'
import { safeParse } from 'valibot'

import { authGuard } from '../../middlewares/auth'
import { enqueueV9VideoObservation, parkDeadLetter, V9_VIDEO_OBSERVATION_DEAD_LETTER } from '../../services/domain/v9-jobs'
import { createBadRequestError } from '../../utils/error'
import { nanoid } from '../../utils/id'
import {
  V9_PAYLOAD_SCHEMAS,
  V9_TOPICS_WITHOUT_PAYLOAD_SCHEMA,
  v9EventEnvelopeSchema,
  v10EventFieldsSchema,
} from './schema'

/**
 * `POST /api/v1/v9/events` —— v9 事件总线的 HTTP 入口（Step B 设计稿 §4）。
 *
 * - 鉴权复用现有通用 API 鉴权中间件 `authGuard`（先例 `routes/chats/index.ts`）。
 * - 传输选 HTTP POST（非 WS RPC）：这条链的目的是**证据**，POST 天然可重试、
 *   失败可观测（非 2xx），与 `idempotency_key` 语义配套。
 * - 校验失败 → 400（带 valibot issues）；DB 失败 → 抛错由全局错误处理转 5xx。
 *   两种失败都**可见**，不静默吞。
 */
/**
 * 新增 topic 却忘了配 payload schema ⇒ 这里直接炸掉，而不是悄悄放行。
 * （"透传"曾经让一次字段名漂移一路绿灯进了生产边界。）
 */
if (V9_TOPICS_WITHOUT_PAYLOAD_SCHEMA.length > 0) {
  throw new Error(
    `v9 topic(s) missing a payload schema: ${V9_TOPICS_WITHOUT_PAYLOAD_SCHEMA.join(', ')}`,
  )
}

/** A 路（纯视频输入）的两个观察 topic：落库后接入 `processVideoObservation` 归约。 */
const VIDEO_OBSERVATION_TOPICS = new Set<string>([
  'aijade.video.observation.webpage_text',
  'aijade.video.observation.video_transcript',
])

/**
 * 把一次 video 观察事件构造成 `V9VideoObservationInput`。
 *
 * `proposalId` **必须是确定性派生的**（`sp_prop_<eventId>`），绝不能用随机数或时间戳：
 * 回放同一事件必须得到同一 proposalId，否则 evidence 闸门（按 proposalId 复算 input_hash）
 * 会在重放时分裂，破坏可复现性。eventId 来自信封，本身由生产者保证唯一且稳定，故
 * `sp_prop_<eventId>` 是幂等且可复现的。
 * 其余字段全部原样取自信封 / payload：
 * - `sessionId` ← payload.session_id（扩展实例级持久安装 id，A 路「会话」身份）；
 * - `traceId` / `correlationId` / `eventId` / `timestamp` / `originDevice` /
 *   `privacyLevel` / `riskScore` ← 信封；
 * - `tick` ← 信封.tick、`inputHash` ← 信封.causality.inputHash（v10 前缀已强制它们存在）；
 * - `event` ← 本次被落库的事件本身（运行时只读 topic + payload）。
 */
function buildVideoObservationInput(
  event: { topic: string, event_id: string, trace_id: string, correlation_id: string, timestamp: number, origin_device: string, privacy_level: 0 | 1 | 2 | 3, risk_score: number, tick?: number, causality?: { inputHash: string } },
  payload: { session_id: string },
): V9VideoObservationInput {
  return {
    eventId: event.event_id,
    sessionId: payload.session_id,
    traceId: event.trace_id,
    correlationId: event.correlation_id,
    timestamp: event.timestamp,
    originDevice: event.origin_device,
    privacyLevel: event.privacy_level,
    riskScore: event.risk_score,
    // tick / inputHash 对 video/learning 前缀是 v10 强制字段（路由已在上方校验），此处存在。
    tick: event.tick as number,
    inputHash: event.causality!.inputHash,
    proposalId: `sp_prop_${event.event_id}`,
    event: event as unknown as AijadeEvent,
  }
}

export function createV9EventsRoutes(v9EventService: V9EventService, runtime?: V9CausalRuntime, redis?: Redis) {
  return new Hono<HonoEnv>()
    .use('*', authGuard)
    .post('/', async (c) => {
      let body: unknown
      try {
        body = await c.req.json()
      }
      catch {
        throw createBadRequestError('Invalid JSON body', 'INVALID_V9_EVENT')
      }
      const result = safeParse(v9EventEnvelopeSchema, body)
      if (!result.success)
        throw createBadRequestError('Invalid v9 event envelope', 'INVALID_V9_EVENT', result.issues)

      const event = result.output
      // v10 video/learning events require deterministic ordering and an
      // explicit provenance hash. Legacy v9 topics remain accepted while
      // producers migrate to the enhanced envelope.
      if (event.topic.startsWith('aijade.video.') || event.topic.startsWith('aijade.learning.')) {
        const v10Result = safeParse(v10EventFieldsSchema, {
          tick: event.tick,
          causality: event.causality,
        })
        if (!v10Result.success) {
          throw createBadRequestError(
            'v10 video/learning events require tick and causality.inputHash',
            'INVALID_V10_EVENT',
            v10Result.issues,
          )
        }
      }
      // 逐 topic 语义校验：这是保证"配对成功 ⟹ 因果成立"的唯一防线。
      const payloadResult = safeParse(V9_PAYLOAD_SCHEMAS[event.topic], event.payload)
      if (!payloadResult.success) {
        throw createBadRequestError(
          `Invalid payload for topic '${event.topic}'`,
          'INVALID_V9_PAYLOAD',
          payloadResult.issues,
        )
      }

      let appended
      try {
        appended = await v9EventService.appendEvent({
          ...event,
          // 用校验通过后的窄化 payload 落库，未知字段不会进 events 表。
          payload: payloadResult.output,
        })
      }
      catch (error) {
        if (error instanceof Error && error.message === 'v10 learning proposal render trace reference or hash mismatch') {
          throw createBadRequestError('Learning proposal render trace does not match the stored projection', 'INVALID_RENDER_TRACE_REFERENCE')
        }
        if (error instanceof Error && (
          error.message === 'v10 render trace render_ref mismatch'
          || error.message === 'v10 render trace intent_ref mismatch'
        )) {
          throw createBadRequestError('Render trace identity does not match the existing projection', 'INVALID_RENDER_TRACE_REFERENCE')
        }
        throw error
      }
      const { row, deduped, pairingMissing } = appended

      // ---- A 路派发：落库成功后，把 video 观察接入内核归约 ----
      // 派发失败**不得**让已落库的事件回滚，也**不得**让响应变成 5xx/400 —— 事件已成功落库
      // 是不可变更的事实。派发问题在此被**记录且可见**（写 dead-letter + 日志），但语义保持
      // "事件已接受"。否则一次 worker/归约抖动会让生产者的 POST 拿到错误码，等于把 sink 的
      // 失败泄漏成上游的失败（与"事件总线只承诺落库"的契约相悖）。
      if (VIDEO_OBSERVATION_TOPICS.has(event.topic) && runtime) {
        const dispatchInput = buildVideoObservationInput(event, payloadResult.output as { session_id: string })
        try {
          if (redis) {
            await enqueueV9VideoObservation(redis, { jobId: nanoid(), input: dispatchInput })
          }
          else {
            // 无 redis ⇒ 降级为内联归约（照 perception 路由的降级语义）。
            await runtime.processVideoObservation(dispatchInput)
          }
        }
        catch (dispatchError) {
          console.error(`[v9-events] video observation dispatch failed for ${event.event_id} (event accepted, not rolled back)`, dispatchError)
          if (redis) {
            await parkDeadLetter(redis, V9_VIDEO_OBSERVATION_DEAD_LETTER, {
              job: { eventId: event.event_id, topic: event.topic },
              error: String(dispatchError),
            })
          }
        }
      }

      return c.json(
        { ok: true, deduped, eventId: row.eventId, pairingMissing: pairingMissing ?? false },
        deduped ? 200 : 201,
      )
    })
}
