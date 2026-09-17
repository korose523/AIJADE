import type { Database } from '../../libs/db'

import { eq, inArray } from 'drizzle-orm'

import { nanoid } from '../../utils/id'

import * as schema from '../../schemas/memory-v9'

/**
 * `render_traces` 投影的**离线回填**（v10 §6.3 / §12.1）。
 *
 * ## 为什么需要
 *
 * 线上投影只在 `appendEvent` 收到渲染相关事件时**增量**写入（`services/domain/v9-events.ts`）。
 * 于是在 v10 之前写入的历史事件、或投影逻辑上线前漏掉的事件，在
 * `render_traces` 里**没有对应行** —— 这会让"学习 B 的轨迹引用"对一段真实发生过的渲染
 * 误判为"引用不存在"。本模块按 `trace_id` 把历史 `events` 里的
 * `persona.render_requested` + `lpm.render_ready` 配对重放成投影行。
 *
 * ## 不变量
 *
 * - **纯规划 + 幂等落地分离**：`planRenderTraceBackfill` 是纯函数（可单测、可直接审阅），
 *   `runRenderTraceBackfill` 只负责把计划落库。
 * - **幂等**：已存在同 `trace_id` 的行则跳过；插入用 `ON CONFLICT DO NOTHING`
 *   （兼容 `render_traces` 上 `render_ref` 的部分唯一索引）。
 * - **不伪造**：缺 `lpm.render_ready`（拿不到 `render_ref` 与两个内容 hash）的 trace
 *   **不生成**投影行，只计入 `incomplete`。宁可留缺口也不编造身份。
 */

export const PERSONA_RENDER_REQUESTED_TOPIC = 'aijade.persona.render_requested'
export const LPM_RENDER_READY_TOPIC = 'aijade.lpm.render_ready'

const RENDER_TOPICS = [PERSONA_RENDER_REQUESTED_TOPIC, LPM_RENDER_READY_TOPIC]

/** 回填的最小输入行（就是 `events` 表里本模块会读的那些列）。 */
export interface RenderBackfillEventRow {
  eventId: string
  traceId: string
  correlationId: string
  topic: string
  payload: Record<string, unknown>
  timestamp: number
}

/** 一条可落库的投影行（字段与 `v9RenderTraces` 逐列对应）。 */
export interface RenderTraceBackfillRow {
  id: string
  sessionId: string
  traceId: string
  correlationId: string
  eventId: string
  personaSnapshotRef: string | null
  intentRef: string | null
  renderRef: string | null
  appliedParamsHash: string | null
  assetVersionHash: string | null
}

export interface RenderBackfillPlan {
  rows: RenderTraceBackfillRow[]
  /** 只有请求没有回执（或缺回执）⇒ 无法构造身份，跳过。 */
  incomplete: { traceId: string, reason: string }[]
  /** 同一 trace 下请求与回执的 `session_id` 不一致 ⇒ 身份链矛盾，跳过。 */
  conflicts: { traceId: string, reason: string }[]
}

function readString(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key]
  return typeof value === 'string' && value.length > 0 ? value : null
}

/**
 * 纯函数：把渲染相关事件行规划成投影行。
 *
 * 确定性：同一输入 ⇒ 同一输出（`id` 由 `trace_id` 派生，不用随机数；重复运行结果一致）。
 */
export function planRenderTraceBackfill(events: RenderBackfillEventRow[]): RenderBackfillPlan {
  const byTrace = new Map<string, RenderBackfillEventRow[]>()
  for (const event of events) {
    const bucket = byTrace.get(event.traceId)
    if (bucket)
      bucket.push(event)
    else
      byTrace.set(event.traceId, [event])
  }

  const rows: RenderTraceBackfillRow[] = []
  const incomplete: { traceId: string, reason: string }[] = []
  const conflicts: { traceId: string, reason: string }[] = []

  for (const [traceId, bucket] of byTrace) {
    const ordered = [...bucket].sort((a, b) => a.timestamp - b.timestamp)
    const request = ordered.find(e => e.topic === PERSONA_RENDER_REQUESTED_TOPIC)
    const ready = ordered.find(e => e.topic === LPM_RENDER_READY_TOPIC)

    if (!ready) {
      incomplete.push({ traceId, reason: 'missing_lpm_render_ready' })
      continue
    }

    const readySession = readString(ready.payload, 'session_id')
    const requestSession = request ? readString(request.payload, 'session_id') : null
    if (request && requestSession && readySession && requestSession !== readySession) {
      conflicts.push({ traceId, reason: 'session_id_mismatch_between_request_and_ready' })
      continue
    }

    const sessionId = readySession ?? requestSession
    if (!sessionId) {
      incomplete.push({ traceId, reason: 'missing_session_id' })
      continue
    }

    rows.push({
      id: `rt_${traceId}`,
      sessionId,
      traceId,
      correlationId: (request ?? ready).correlationId,
      eventId: ready.eventId,
      personaSnapshotRef: request ? readString(request.payload, 'persona_snapshot_ref') : null,
      intentRef: request ? readString(request.payload, 'intent_ref') : null,
      renderRef: readString(ready.payload, 'render_ref'),
      appliedParamsHash: readString(ready.payload, 'applied_params_hash'),
      assetVersionHash: readString(ready.payload, 'asset_version_hash'),
    })
  }

  // 稳定排序，便于审计与快照比对。
  rows.sort((a, b) => a.traceId.localeCompare(b.traceId))
  return { rows, incomplete, conflicts }
}

export interface RenderBackfillReport {
  scannedEvents: number
  plannedRows: number
  inserted: number
  skippedExisting: number
  /** 因唯一索引冲突（例如同 `render_ref` 已属另一 trace）而未插入。 */
  skippedConflict: number
  incomplete: { traceId: string, reason: string }[]
  conflicts: { traceId: string, reason: string }[]
}

export interface RenderBackfillOptions {
  /** 只规划不落库（干跑），用于审计在真实库上会改什么。 */
  dryRun?: boolean
}

/**
 * 读历史事件 → 规划 → 幂等落库。可跑在 PGlite 与真实 PostgreSQL 上（同一 drizzle 代码路径）。
 */
export async function runRenderTraceBackfill(
  db: Database,
  options: RenderBackfillOptions = {},
): Promise<RenderBackfillReport> {
  const scanned = await db
    .select({
      eventId: schema.v9Events.eventId,
      traceId: schema.v9Events.traceId,
      correlationId: schema.v9Events.correlationId,
      topic: schema.v9Events.topic,
      payload: schema.v9Events.payload,
      timestamp: schema.v9Events.timestamp,
    })
    .from(schema.v9Events)
    .where(inArray(schema.v9Events.topic, RENDER_TOPICS))
    .orderBy(schema.v9Events.timestamp)

  const events: RenderBackfillEventRow[] = scanned.map(row => ({
    eventId: row.eventId,
    traceId: row.traceId,
    correlationId: row.correlationId,
    topic: row.topic,
    payload: (row.payload ?? {}) as Record<string, unknown>,
    timestamp: row.timestamp instanceof Date ? row.timestamp.getTime() : Number(row.timestamp),
  }))

  const plan = planRenderTraceBackfill(events)

  let inserted = 0
  let skippedExisting = 0
  let skippedConflict = 0

  if (!options.dryRun) {
    for (const row of plan.rows) {
      const existing = await db
        .select({ id: schema.v9RenderTraces.id })
        .from(schema.v9RenderTraces)
        .where(eq(schema.v9RenderTraces.traceId, row.traceId))

      if (existing.length > 0) {
        skippedExisting++
        continue
      }

      const written = await db
        .insert(schema.v9RenderTraces)
        .values({
          id: row.id || nanoid(),
          sessionId: row.sessionId,
          traceId: row.traceId,
          correlationId: row.correlationId,
          eventId: row.eventId,
          personaSnapshotRef: row.personaSnapshotRef,
          intentRef: row.intentRef,
          renderRef: row.renderRef,
          appliedParamsHash: row.appliedParamsHash,
          assetVersionHash: row.assetVersionHash,
          createdAt: new Date(),
          updatedAt: new Date(),
        })
        .onConflictDoNothing()
        .returning({ id: schema.v9RenderTraces.id })

      if (written.length > 0)
        inserted++
      else
        skippedConflict++
    }
  }

  return {
    scannedEvents: events.length,
    plannedRows: plan.rows.length,
    inserted,
    skippedExisting,
    skippedConflict,
    incomplete: plan.incomplete,
    conflicts: plan.conflicts,
  }
}
