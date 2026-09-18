import type { Database } from '../../libs/db'

import { useLogger } from '@guiiai/logg'
import { and, desc, eq, isNotNull, sql } from 'drizzle-orm'

import { nanoid } from '../../utils/id'

import * as schema from '../../schemas/memory-v9'

const logger = useLogger('v9-events')

const PERSONA_RENDER_REQUESTED = 'aijade.persona.render_requested'
const LPM_RENDER_READY = 'aijade.lpm.render_ready'

/**
 * 渲染轨迹契约的失败原因。
 *
 * 为什么要分成可区分的 reason：v10 §6.4 的三条 reject 规则
 * （`render_ref` 不存在 / `applied_params_hash` 不一致 / `asset_version_hash` 不一致）
 * 此前被合并成**同一个** `Error` 与同一句消息，于是"缺配"和"漂移"在日志里完全无法区分 ——
 * 而这两者的处置方式不同（前者可能是回填没跑，后者是身份被篡改）。§11.2 还额外要求
 * "自引用冒充"必须被拒，也需要自己的 reason。
 */
export type RenderTraceContractFailureReason
  = | 'render_ref_not_found'
    | 'intent_ref_missing'
    | 'applied_params_hash_mismatch'
    | 'asset_version_hash_mismatch'
    | 'self_reference'
    | 'projection_render_ref_mismatch'
    | 'projection_intent_ref_mismatch'

/**
 * 渲染轨迹契约被违反。
 *
 * 用**类型**而不是"匹配错误消息字符串"来表达：路由层原先靠
 * `error.message === 'v10 learning proposal render trace reference or hash mismatch'`
 * 精确比对来决定是否转 400 —— 消息一改（例如为了让人看清是哪一条规则失败），
 * 401/400 的映射就会静默失效，变成一个 500。类型检查能挡住这种回归。
 */
export class RenderTraceContractError extends Error {
  readonly reason: RenderTraceContractFailureReason

  constructor(reason: RenderTraceContractFailureReason, detail: string) {
    super(`v10 render trace contract violated: ${reason} (${detail})`)
    this.name = 'RenderTraceContractError'
    this.reason = reason
  }
}

/**
 * 该 reason 对应的**对外消息**。刻意与重构前的两句原文逐字一致 ——
 * HTTP 契约（400 + `INVALID_RENDER_TRACE_REFERENCE` + 消息）对外保持不变，
 * 只有服务端日志里多了可区分的 reason。
 */
export function renderTraceFailureMessage(reason: RenderTraceContractFailureReason): string {
  switch (reason) {
    case 'projection_render_ref_mismatch':
    case 'projection_intent_ref_mismatch':
      return 'Render trace identity does not match the existing projection'
    default:
      return 'Learning proposal render trace does not match the stored projection'
  }
}

/**
 * v10 §6.2 / 报告 P1-2 的投影完成标记。
 *
 * `paired` = 请求 (`intent_ref`) 与回执 (`render_ref`) 齐备，身份链完整；
 * `partial` = 只收到一端，存在配对缺口。把"缺配"从不可见变成可查的状态位，
 * 而不是把缺口埋成正常数据骗过论文。
 */
export type ProjectionStatus = 'partial' | 'paired'

export function projectionStatusOf(renderRef: string | null, intentRef: string | null): ProjectionStatus {
  return renderRef && intentRef ? 'paired' : 'partial'
}

export interface V9EventInput {
  event_id: string
  trace_id: string
  correlation_id: string
  /** unix ms */
  timestamp: number
  producer: string
  /**
   * 观察/传输上下文。**必填**（与内核信封、HTTP 边界同集）。
   *
   * 这里原本是 `origin_device?` / `privacy_level?` … 可选，并在落库时用
   * `input.origin_device ?? input.producer` 之类的兜底**合成**缺失值：那会把 `producer`
   * 当设备名写进 `origin_device` 列 —— 一个凭空造出来的"设备"。既然内核信封与边界
   * schema 都已要求这 5 个字段，这一层就没有理由再允许缺省；缺省只会掩盖调用方漏传。
   */
  origin_device: string
  privacy_level: 0 | 1 | 2 | 3
  evidence_refs: string[]
  causal_context_refs: string[]
  risk_score: number
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
  /**
   * 最近一条回执三元组齐备的真实渲染身份（复核报告 R1）。
   * 供 A 路观察派发注入 `learning.proposed.evidence` 的真实 ref；无则 `null`
   * （宁缺勿伪造，调用方必须跳过派发）。
   */
  findLatestRenderIdentity: () => Promise<RenderTraceReference | null>
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

  // v10 §6.2 / 报告 P1-2：两个事件 id 来自各自 topic 的 `event_id`。
  // 可为 undefined（对应列可为空）—— 因为投影行可能先由另一端的事件建立。
  const renderReadyEventId = input.topic === LPM_RENDER_READY ? input.event_id : undefined
  const personaRenderRequestedEventId = input.topic === PERSONA_RENDER_REQUESTED ? input.event_id : undefined

  // §11.2「自引用冒充」：身份字段（`intent_ref` / `render_ref`）指向**信封自身的标识**
  // —— 它不指向任何真实对象，只是把信封上的 trace/event/correlation 抄了一遍。
  // 这类值在后续跨事件回填补齐时会被当成"两个不同 topic 指向同一身份"的**假证据**，
  // 因此必须在写入投影前拒绝。放在投影层而非 payload schema：这是**跨字段语义规则**，
  // 单看 payload 无法判定（schema 不知道 ref 与 trace_id 的关系）。
  const envelopeIdentities = new Set([input.trace_id, input.event_id, input.correlation_id])
  for (const [field, value] of [
    ['intent_ref', startValues.intentRef],
    ['render_ref', startValues.renderRef],
  ] as const) {
    if (value && envelopeIdentities.has(value)) {
      throw new RenderTraceContractError(
        'self_reference',
        `${field}=${value} equals an envelope identifier (trace=${input.trace_id})`,
      )
    }
  }

  if (existingTrace[0]) {
    // A trace is an append-only identity chain. Never silently replace a
    // render or intent with a second value under the same trace.
    if (input.topic === LPM_RENDER_READY
      && existingTrace[0].renderRef
      && existingTrace[0].renderRef !== startValues.renderRef) {
      throw new RenderTraceContractError('projection_render_ref_mismatch', `trace=${input.trace_id}`)
    }
    if (input.topic === PERSONA_RENDER_REQUESTED
      && existingTrace[0].intentRef
      && existingTrace[0].intentRef !== startValues.intentRef) {
      throw new RenderTraceContractError('projection_intent_ref_mismatch', `trace=${input.trace_id}`)
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
        renderReadyEventId: renderReadyEventId ?? existingTrace[0].renderReadyEventId,
        personaRenderRequestedEventId: personaRenderRequestedEventId ?? existingTrace[0].personaRenderRequestedEventId,
        projectionStatus: projectionStatusOf(
          startValues.renderRef ?? existingTrace[0].renderRef,
          startValues.intentRef ?? existingTrace[0].intentRef,
        ),
        updatedAt: new Date(),
      })
      .where(eq(schema.v9RenderTraces.id, existingTrace[0].id))
    return
  }

  await dbClient.insert(schema.v9RenderTraces).values({
    id: nanoid(),
    ...startValues,
    renderReadyEventId: renderReadyEventId ?? null,
    personaRenderRequestedEventId: personaRenderRequestedEventId ?? null,
    projectionStatus: projectionStatusOf(startValues.renderRef, startValues.intentRef),
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
   * 取最近一条「回执三元组齐备」的真实渲染投影（`lpm.render_ready` 落库片段）。
   *
   * 复核报告 R1（B/C 路真实生产者）：A 路观察派发构建 `learning.proposed.evidence`
   * 时，渲染身份**必须**来自本查询返回的真实投影行——宁缺勿伪造：查不到即返回
   * `null`，调用方（events 路由派发）必须跳过提案，绝不合成（v10 §14.4 / P0-2）。
   *
   * 语义：AIJADE 是自托管单用户 companion，"当前活跃渲染轨迹"＝服务端最近一次
   * 真实回执。**不做 session 级 join**：扩展观察的 `session_id` 是扩展安装 id，
   * 与 stage-ui 渲染回执的会话 id 分属不同命名空间（见扩展 `client.ts` 顶部不变量
   * 注释）；二者的可信联结点就是本投影表本身。提案随后被引用时，边界侧
   * `validateLearningReference`（render_ref 存在 + hash 一致）仍会独立复核，
   * 因此本查询放宽到"三元组齐备的最新行"（含 `partial` 行——回执先到时三元组
   * 已完整）不构成伪造风险。
   */
  async function findLatestRenderIdentity(): Promise<RenderTraceReference | null> {
    const [row] = await db.select({
      renderRef: schema.v9RenderTraces.renderRef,
      appliedParamsHash: schema.v9RenderTraces.appliedParamsHash,
      assetVersionHash: schema.v9RenderTraces.assetVersionHash,
    })
      .from(schema.v9RenderTraces)
      .where(and(
        isNotNull(schema.v9RenderTraces.renderRef),
        isNotNull(schema.v9RenderTraces.appliedParamsHash),
        isNotNull(schema.v9RenderTraces.assetVersionHash),
      ))
      .orderBy(desc(schema.v9RenderTraces.updatedAt), desc(schema.v9RenderTraces.createdAt))
      .limit(1)
    if (!row?.renderRef || !row.appliedParamsHash || !row.assetVersionHash)
      return null
    return {
      renderRef: row.renderRef,
      appliedParamsHash: row.appliedParamsHash,
      assetVersionHash: row.assetVersionHash,
    }
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
    const renderRef = String(payload.render_ref)

    // §11.2 点名的「自引用冒充」：ref 指向 trace / event 自己，等于用信封自身的标识
    // 冒充一次真实渲染身份。此前该形状被**显式记为已知缺口**（矩阵里只注释、不断言），
    // 于是"配对该拦住的形状"实际能穿过引用校验。
    if (
      renderRef === input.trace_id
      || renderRef === input.event_id
      || renderRef === input.idempotency_key
    ) {
      throw new RenderTraceContractError(
        'self_reference',
        `render_ref=${renderRef} equals trace_id/event_id/idempotency_key (trace=${input.trace_id})`,
      )
    }

    const [trace] = await dbClient.select().from(schema.v9RenderTraces).where(eq(schema.v9RenderTraces.renderRef, renderRef)).limit(1)

    // 三条规则**分别**判定、分别给出 reason（§6.4）。合并成单条件会把
    // 「缺配（回填没跑）」与「漂移（身份被改）」压成同一句话，审计时无法定位。
    if (!trace)
      throw new RenderTraceContractError('render_ref_not_found', `render_ref=${renderRef}`)
    if (!trace.intentRef)
      throw new RenderTraceContractError('intent_ref_missing', `render_ref=${renderRef}`)
    if (trace.appliedParamsHash !== payload.applied_params_hash) {
      throw new RenderTraceContractError(
        'applied_params_hash_mismatch',
        `render_ref=${renderRef} stored=${String(trace.appliedParamsHash)} proposed=${String(payload.applied_params_hash)}`,
      )
    }
    if (trace.assetVersionHash !== payload.asset_version_hash) {
      throw new RenderTraceContractError(
        'asset_version_hash_mismatch',
        `render_ref=${renderRef} stored=${String(trace.assetVersionHash)} proposed=${String(payload.asset_version_hash)}`,
      )
    }
    // ⚠️ 已知边界：`intent_ref` 只能校验"存在"，无法与提案比对 —— v10 §5.4 的
    // `learning.proposed.*` payload 只携带 `render_ref` + 两个 hash，没有第二个域身份可对照。
    // 若将来要让"引用域一致"真正可判定，需要给提案 payload 增加域标识，而不是在此发明比较。
  }

  return {
    findRenderTrace,
    isRenderTraceConsistent,
    findLatestRenderIdentity,
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
          // 直接采用调用方给的真实观察上下文，**不做兜底合成** —— 兜底会把漏传静默变成
          // 一个看起来合法的假值（例如把 producer 当设备名）。类型上已是必填，故此处无 `??`。
          originDevice: input.origin_device,
          privacyLevel: input.privacy_level,
          evidenceRefs: input.evidence_refs,
          causalContextRefs: input.causal_context_refs,
          riskScore: input.risk_score,
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
