import type { Database } from '../../libs/db'

import { useLogger } from '@guiiai/logg'
import { and, eq } from 'drizzle-orm'

import { nanoid } from '../../utils/id'

import * as schema from '../../schemas/memory-v9'

const logger = useLogger('v9-events')

const PERSONA_RENDER_REQUESTED = 'aijade.persona.render_requested'
const LPM_RENDER_READY = 'aijade.lpm.render_ready'

export interface V9EventInput {
  event_id: string
  trace_id: string
  correlation_id: string
  /** unix ms */
  timestamp: number
  producer: string
  idempotency_key: string
  replay_mode: 'live' | 'replay'
  risk_level: 'low' | 'medium' | 'high'
  topic: string
  payload: Record<string, unknown>
}

export interface V9EventRow {
  id: string
  eventId: string
  traceId: string
  correlationId: string
  topic: string
  idempotencyKey: string
}

export interface AppendEventResult {
  row: V9EventRow
  /** 同一 idempotency_key 重复提交 → true（行已存在，未新增）。 */
  deduped: boolean
  /** 仅对 `lpm.render_ready`：同 trace 找不到 `persona.render_requested` 时为 true。 */
  pairingMissing?: boolean
}

export interface V9EventService {
  appendEvent: (input: V9EventInput) => Promise<AppendEventResult>
}

/**
 * v9 统一事件总线的唯一写入口（Step B 设计稿 §3）。
 *
 * 不变量（最小闭环也必须成立，见设计稿 §6）：
 * 1. **失败必须可见**：DB 写入失败抛错，由路由层转 5xx；绝不静默返回成功。
 * 2. **幂等靠唯一键**：先查 `idempotency_key` 是否已存在（幂等去重，不依赖各驱动的
 *    `rowCount` 行为），再 `ON CONFLICT DO NOTHING` 兜底；客户端重试是常态。
 * 3. **不在服务端重算指纹**：`applied_params_hash` 原样落 jsonb，服务端只校验不重算。
 * 4. **配对校验**：`lpm.render_ready` 到手时反查同 trace 的 `persona.render_requested`，
 *    缺口写入 `audit_log_entries`——这正是 P4「可复现性被工程化保证」的可查证据。
 */
export function createV9EventService(db: Database): V9EventService {
  /**
   * 仅对 `lpm.render_ready` 做配对校验：反查同 trace 的请求事件，缺失则记审计缺口。
   * 返回 true 表示"回执没有忠于任何已知意图"（可见的缺口，不是失败）。
   */
  async function checkRenderReadyPairing(input: V9EventInput): Promise<boolean> {
    if (input.topic !== LPM_RENDER_READY)
      return false
    const [request] = await db.select({ id: schema.v9Events.id })
      .from(schema.v9Events)
      .where(and(
        eq(schema.v9Events.topic, PERSONA_RENDER_REQUESTED),
        eq(schema.v9Events.traceId, input.trace_id),
      ))
      .limit(1)
    if (request)
      return false
    // 配对缺口：写入审计（表已存在：memory-v9.ts 的 v9AuditLogEntries）。这是 P4 证据
    // 链的可查缺口标记，不是失败——它让"渲染没有忠于任何已知意图"变得可见，而非
    // 被当成正常数据埋进论文。
    await db.insert(schema.v9AuditLogEntries).values({
      id: nanoid(),
      txId: input.event_id,
      actor: 'v9-render-pairing',
      action: 'render_ready_without_matching_request',
      beforeHash: null,
      afterHash: input.trace_id,
      at: new Date(),
    })
    logger.withFields({ traceId: input.trace_id, idempotencyKey: input.idempotency_key })
      .warn('lpm.render_ready received without a matching persona.render_requested in the same trace')
    return true
  }

  function readByIdempotencyKey(k: string) {
    return db.select({
      id: schema.v9Events.id,
      eventId: schema.v9Events.eventId,
      traceId: schema.v9Events.traceId,
      correlationId: schema.v9Events.correlationId,
      topic: schema.v9Events.topic,
      idempotencyKey: schema.v9Events.idempotencyKey,
    }).from(schema.v9Events).where(eq(schema.v9Events.idempotencyKey, k)).limit(1)
  }

  return {
    async appendEvent(input: V9EventInput): Promise<AppendEventResult> {
      // 先查是否已存在同 idempotency_key（幂等去重，跨驱动稳健；不信赖 rowCount）。
      const [existing] = await readByIdempotencyKey(input.idempotency_key)
      if (existing) {
        // 幂等重放：行已存在即直接返回，**不再**重复做配对校验——否则每次重试都会
        // 再插一条审计缺口，把 P4 的证据链污染成噪声。
        return { row: existing, deduped: true }
      }

      await db.insert(schema.v9Events).values({
        id: nanoid(),
        eventId: input.event_id,
        traceId: input.trace_id,
        correlationId: input.correlation_id,
        timestamp: new Date(input.timestamp),
        producer: input.producer,
        topic: input.topic,
        payload: input.payload,
        idempotencyKey: input.idempotency_key,
        replayMode: input.replay_mode,
        riskLevel: input.risk_level,
      }).onConflictDoNothing({ target: schema.v9Events.idempotencyKey })

      const [row] = await readByIdempotencyKey(input.idempotency_key)
      if (!row) {
        // ON CONFLICT DO NOTHING + 唯一约束下总能 select 到一行（既有或新建）。
        // 走到这里说明 DB 异常——必须可见，不能静默返回成功。
        throw new Error('v9-events: failed to read back inserted event row after upsert')
      }

      const pairingMissing = await checkRenderReadyPairing(input)
      return { row, deduped: false, pairingMissing }
    },
  }
}
