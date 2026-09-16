import type { V9EventService } from '../../services/domain/v9-events'
import type { HonoEnv } from '../../types/hono'

import { Hono } from 'hono'
import { safeParse } from 'valibot'

import { authGuard } from '../../middlewares/auth'
import { createBadRequestError } from '../../utils/error'
import { v9EventEnvelopeSchema } from './schema'

/**
 * `POST /api/v1/v9/events` —— v9 事件总线的 HTTP 入口（Step B 设计稿 §4）。
 *
 * - 鉴权复用现有通用 API 鉴权中间件 `authGuard`（先例 `routes/chats/index.ts`）。
 * - 传输选 HTTP POST（非 WS RPC）：这条链的目的是**证据**，POST 天然可重试、
 *   失败可观测（非 2xx），与 `idempotency_key` 语义配套。
 * - 校验失败 → 400（带 valibot issues）；DB 失败 → 抛错由全局错误处理转 5xx。
 *   两种失败都**可见**，不静默吞。
 */
export function createV9EventsRoutes(v9EventService: V9EventService) {
  return new Hono<HonoEnv>()
    .use('*', authGuard)
    .post('/', async (c) => {
      const body = await c.req.json()
      const result = safeParse(v9EventEnvelopeSchema, body)
      if (!result.success)
        throw createBadRequestError('Invalid v9 event envelope', 'INVALID_V9_EVENT', result.issues)

      const { row, deduped, pairingMissing } = await v9EventService.appendEvent(result.output)
      return c.json(
        { ok: true, deduped, eventId: row.eventId, pairingMissing: pairingMissing ?? false },
        deduped ? 200 : 201,
      )
    })
}
