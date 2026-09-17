import type { Database } from '../../libs/db'

import { useLogger } from '@guiiai/logg'
import { and, eq, sql } from 'drizzle-orm'

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
  origin_device?: string
  privacy_level?: 0 | 1 | 2 | 3
  evidence_refs?: string[]
  causal_context_refs?: string[]
  risk_score?: number
  idempotency_key: string
  replay_mode: 'live' | 'replay'
  risk_level: 'low' | 'medium' | 'high'
  tick?: number
  causality?: { inputHash: string }
  /** v10 内生状态节点（S0..S8），由客户端/内核信封传播而来。 */
  core_state_node?: string
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

export interface RenderTraceReference {
  renderRef: string
  appliedParamsHash: string
  assetVersionHash: string
  intentRef?: string
}

export type RenderTraceRecord = typeof schema.v9RenderTraces.$inferSelect

export interface V9EventService {
  appendEvent: (input: V9EventInput) => Promise<AppendEventResult>
  /** 查找可供学习/回放引用的渲染投影。 */
  findRenderTrace: (renderRef: string) => Promise<RenderTraceRecord | null>
  /** 校验 render、intent 及两个内容 hash 是否属于同一条投影。 */
  isRenderTraceConsistent: (reference: RenderTraceReference) => Promise<boolean>
}

type EventDbLike = Pick<Database, 'select' | 'insert' | 'update'>

function readByIdempotencyKeyFrom(dbClient: EventDbLike, k: string) {
  return dbClient.select({
    id: schema.v9Events.id,
    eventId: schema.v9Events.eventId,
    traceId: schema.v9Events.traceId,
    correlationId: schema.v9Events.correlationId,
    topic: schema.v9Events.topic,
    idempotencyKey: schema.v9Events.idempotencyKey,
  }).from(schema.v9Events).where(eq(schema.v9Events.idempotencyKey, k)).limit(1)
}

async function upsertRenderTraceProjection(dbClient: EventDbLike, input: V9EventInput): Promise<void> {
  if (input.topic !== PERSONA_RENDER_REQUESTED && input.topic !== LPM_RENDER_READY)
    return
  const payload = input.payload as Record<string, unknown>

  const existingTrace = await dbClient.select()
    .from(schema.v9RenderTraces)
    .where(eq(schema.v9RenderTraces.traceId, input.trace_id))
    .limit(1)

  const startValues = {
    sessionId: String(payload.session_id ?? ''),
    traceId: input.trace_id,
    correlationId: input.correlation_id,
    eventId: input.event_id,
    personaSnapshotRef: payload.persona_snapshot_ref == null ? null : String(payload.persona_snapshot_ref),
    intentRef: payload.intent_ref == null ? null : String(payload.intent_ref),
    renderRef: payload.render_ref == null ? null : String(payload.render_ref),
    appliedParamsHash: payload.applied_params_hash == null ? null : String(payload.applied_params_hash),
    assetVersionHash: payload.asset_version_hash == null ? null : String(payload.asset_version_hash),
  }

  if (existingTrace[0]) {
    // A trace is an append-only identity chain. Never silently replace a
    // render or intent with a second value under the same trace.
    if (input.topic === LPM_RENDER_READY
      && existingTrace[0].renderRef
      && existingTrace[0].renderRef !== startValues.renderRef) {
      throw new Error('v10 render trace render_ref mismatch')
    }
    if (input.topic === PERSONA_RENDER_REQUESTED
      && existingTrace[0].intentRef
      && existingTrace[0].intentRef !== startValues.intentRef) {
      throw new Error('v10 render trace intent_ref mismatch')
    }
    await dbClient.update(schema.v9RenderTraces)
      .set({
        sessionId: startValues.sessionId,
        correlationId: startValues.correlationId,
        eventId: startValues.eventId,
        personaSnapshotRef: startValues.personaSnapshotRef ?? existingTrace[0].personaSnapshotRef,
        intentRef: startValues.intentRef ?? existingTrace[0].intentRef,
        renderRef: startValues.renderRef ?? existingTrace[0].renderRef,
        appliedParamsHash: startValues.appliedParamsHash ?? existingTrace[0].appliedParamsHash,
        assetVersionHash: startValues.assetVersionHash ?? existingTrace[0].assetVersionHash,
        updatedAt: new Date(),
      })
      .where(eq(schema.v9RenderTraces.id, existingTrace[0].id))
    return
  }

  await dbClient.insert(schema.v9RenderTraces).values({
    id: nanoid(),
    ...startValues,
    createdAt: new Date(),
    updatedAt: new Date(),
  })
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
  async function findRenderTrace(renderRef: string): Promise<RenderTraceRecord | null> {
    if (!renderRef)
      return null
    const [trace] = await db.select()
      .from(schema.v9RenderTraces)
      .where(eq(schema.v9RenderTraces.renderRef, renderRef))
      .limit(1)
    return trace ?? null
  }

  async function isRenderTraceConsistent(reference: RenderTraceReference): Promise<boolean> {
    const trace = await findRenderTrace(reference.renderRef)
    return Boolean(trace
      && trace.intentRef
      && (!reference.intentRef || trace.intentRef === reference.intentRef)
      && trace.appliedParamsHash === reference.appliedParamsHash
      && trace.assetVersionHash === reference.assetVersionHash)
  }

  /**
   * 仅对 `lpm.render_ready` 做配对校验：反查同 trace 的请求事件，缺失则记审计缺口。
   * 返回 true 表示"回执没有忠于任何已知意图"（可见的缺口，不是失败）。
   */
  async function checkRenderReadyPairing(dbClient: EventDbLike, input: V9EventInput): Promise<boolean> {
    if (input.topic !== LPM_RENDER_READY)
      return false
    const [request] = await dbClient.select({ id: schema.v9Events.id })
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
    await dbClient.insert(schema.v9AuditLogEntries).values({
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

  async function validateLearningReference(dbClient: EventDbLike, input: V9EventInput): Promise<void> {
    if (!input.topic.startsWith('aijade.learning.proposed.'))
      return
    const payload = input.payload
    const [trace] = await dbClient.select().from(schema.v9RenderTraces).where(eq(schema.v9RenderTraces.renderRef, String(payload.render_ref))).limit(1)
    if (!trace
      || !trace.intentRef
      || trace.appliedParamsHash !== payload.applied_params_hash
      || trace.assetVersionHash !== payload.asset_version_hash) {
      throw new Error('v10 learning proposal render trace reference or hash mismatch')
    }
  }

  return {
    findRenderTrace,
    isRenderTraceConsistent,
    async appendEvent(input: V9EventInput): Promise<AppendEventResult> {
      const [existing] = await readByIdempotencyKeyFrom(db, input.idempotency_key)
      if (existing) {
        return { row: existing, deduped: true }
      }

      return await db.transaction(async (tx) => {
        const [txExisting] = await readByIdempotencyKeyFrom(tx as EventDbLike, input.idempotency_key)
        if (txExisting) {
          return { row: txExisting, deduped: true }
        }

        await validateLearningReference(tx as EventDbLike, input)
        const eventValues = {
          id: nanoid(),
          eventId: input.event_id,
          traceId: input.trace_id,
          correlationId: input.correlation_id,
          timestamp: new Date(input.timestamp),
          producer: input.producer,
          originDevice: input.origin_device ?? input.producer,
          privacyLevel: input.privacy_level ?? 1,
          evidenceRefs: input.evidence_refs ?? [],
          causalContextRefs: input.causal_context_refs ?? [input.trace_id],
          riskScore: input.risk_score ?? 0,
          topic: input.topic,
          payload: input.payload,
          idempotencyKey: input.idempotency_key,
          replayMode: input.replay_mode,
          riskLevel: input.risk_level,
          ...(input.tick === undefined ? {} : { tick: input.tick }),
          ...(input.causality === undefined ? {} : { causality: input.causality }),
          ...(input.core_state_node === undefined ? {} : { coreStateNode: input.core_state_node }),
        }
        // 只要带了任一 v10 字段就必须走 drizzle 分支（原始 SQL 回退分支不写这些列，
        // 否则 `core_state_node` 会被静默丢弃）。
        if (input.tick === undefined && input.causality === undefined && input.core_state_node === undefined) {
          // Keep the v9 write path compatible with databases that have not
          // applied the additive v10 migration yet.
          await tx.execute(sql`INSERT INTO "events"
            ("id", "event_id", "trace_id", "correlation_id", "timestamp", "producer",
             "origin_device", "privacy_level", "evidence_refs", "causal_context_refs",
             "risk_score", "topic", "payload", "idempotency_key", "replay_mode", "risk_level")
            VALUES (${eventValues.id}, ${eventValues.eventId}, ${eventValues.traceId},
              ${eventValues.correlationId}, ${eventValues.timestamp}, ${eventValues.producer},
              ${eventValues.originDevice}, ${eventValues.privacyLevel},
              ARRAY[${sql.join(eventValues.evidenceRefs.map(value => sql`${value}`), sql`, `)}]::text[],
              ARRAY[${sql.join(eventValues.causalContextRefs.map(value => sql`${value}`), sql`, `)}]::text[],
              ${eventValues.riskScore}, ${eventValues.topic},
              ${eventValues.payload}, ${eventValues.idempotencyKey}, ${eventValues.replayMode},
              ${eventValues.riskLevel})
            ON CONFLICT ("idempotency_key") DO NOTHING`)
        }
        else {
          await tx.insert(schema.v9Events).values(eventValues).onConflictDoNothing({ target: schema.v9Events.idempotencyKey })
        }

        const [row] = await readByIdempotencyKeyFrom(tx as EventDbLike, input.idempotency_key)
        if (!row) {
          throw new Error('v9-events: failed to read back inserted event row after upsert')
        }

        const pairingMissing = await checkRenderReadyPairing(tx as EventDbLike, input)
        await upsertRenderTraceProjection(tx as EventDbLike, input)
        return { row, deduped: false, pairingMissing }
      })
    },
  }
}
