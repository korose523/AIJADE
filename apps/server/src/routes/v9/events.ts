import type { V9EventService } from '../../services/domain/v9-events'
import type { HonoEnv } from '../../types/hono'

import { Hono } from 'hono'
import { safeParse } from 'valibot'

import { authGuard } from '../../middlewares/auth'
import { createBadRequestError } from '../../utils/error'
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

export function createV9EventsRoutes(v9EventService: V9EventService) {
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
      return c.json(
        { ok: true, deduped, eventId: row.eventId, pairingMissing: pairingMissing ?? false },
        deduped ? 200 : 201,
      )
    })
}
