import type { Database } from '../../libs/db'
import type { HonoEnv } from '../../types/hono'

import { computeV6WMaxBounds, deriveCoreStateNode, PGC_V6_PARAMS_CASE4 } from '@proj-aijade/memory-biomimetic'
import { and, eq, inArray, sql } from 'drizzle-orm'
import { Hono } from 'hono'
import { safeParse } from 'valibot'

import { authGuard } from '../../middlewares/auth'
import { createBadRequestError } from '../../utils/error'
import { v9ReplaySchema } from './schema'

import * as schema from '../../schemas/memory-v9'

/**
 * `POST /api/v1/v9/replay` —— v10 §4.3 / §11.3 的**回放一致性校验**入口。
 *
 * 语义：给定 `tick` + `causality.inputHash`（即"同一输入快照"），把该快照下**已被记录**的
 * 内生事实与**现在用当前代码复算**出的值逐一比对，从而把"契约/代码漂移"变成可检出的失败。
 *
 * ## 为什么这不是恒真式（本模块存在的全部理由）
 *
 * 三条检查里，**没有一条**是"把记录值抄回来跟自己比"：
 *
 * 1. `core_state_node`：复算输入是 `deriveCoreStateNode(topic, { hasMemoryVersion })`，
 *    其中 `hasMemoryVersion` 是**从 `memory_versions`/`memory_txs` 现查回来的数据库事实**，
 *    不是被记录的那个节点。⇒ 若某行的节点标错（或 `S8` 与真实落库不符），比对必然失败。
 * 2. `w_max_global` / `w_max_at_f`（§4.3 明确点名）：
 *    复算输入是持久化的 `pgc_states.v6_state.tau` 与 `.s.f`，经**当前的**
 *    `computeV6WMaxBounds` 重算，再与持久化的 `w_max_*` 比对。⇒ 只要该函数或其常数
 *    （`PGC_V6_PARAMS_CASE4`）变了，历史行就会报漂移。这正是我们想要的跨版本守卫。
 * 3. `commit_reason`：必须是 `pgc.ts` 固定判定链上的成员；出现链外取值即报漂移。
 *
 * ## 诚实降级
 *
 * 若某行**没有** `core_state_node`（v10 之前写入的旧行），本模块**不会**把它当成"一致"，
 * 而是报告 `insufficient_input_snapshot` 并列出缺什么 —— 缺证据就是缺证据。
 */

/** `pgc.ts` 固定的 `commit_reason` 判定链（顺序即语义，勿改）。 */
const COMMIT_REASON_CHAIN = [
  'w_max_below_theta',
  'contradiction_high',
  'evidence_insufficient',
  'fatigue_deferred',
  'w_below_theta',
  'committed',
] as const

/** 浮点比较容差：复算与记录都来自同一确定性函数，仅用于吸收 jsonb 往返噪声。 */
const FLOAT_EPSILON = 1e-12

/** `pgc_states.v6_state` 里本模块真正消费的字段（最小读取口径，不做二次变换）。 */
interface PersistedV6State {
  tau: 'episodic' | 'affective' | 'procedural' | 'semantic'
  s: { f: number }
  w_max_global: number
  w_max_at_f: number
  commit_reason: string
}

interface ReplayMismatch {
  kind: string
  eventId?: string
  traceId?: string
  topic?: string
  recorded?: string | number | null
  recomputed?: string | number
}

interface ReplayInsufficient {
  kind: string
  traceId?: string
  eventId?: string
  missing: string[]
}

export function createV9ReplayRoutes(db: Database) {
  return new Hono<HonoEnv>()
    .use('*', authGuard)
    .post('/', async (c) => {
      let body: unknown
      try {
        body = await c.req.json()
      }
      catch {
        throw createBadRequestError('Invalid JSON body', 'INVALID_V9_REPLAY')
      }
      const parsed = safeParse(v9ReplaySchema, body)
      if (!parsed.success)
        throw createBadRequestError('Invalid v9 replay request', 'INVALID_V9_REPLAY', parsed.issues)

      const { tick, inputHash } = parsed.output

      const events = await db
        .select({
          eventId: schema.v9Events.eventId,
          traceId: schema.v9Events.traceId,
          topic: schema.v9Events.topic,
          coreStateNode: schema.v9Events.coreStateNode,
        })
        .from(schema.v9Events)
        .where(and(
          eq(schema.v9Events.tick, tick),
          sql`${schema.v9Events.causality} ->> 'inputHash' = ${inputHash}`,
        ))

      if (events.length === 0) {
        // 没有该输入快照的事件 ⇒ 明确失败，绝不返回"一致"。
        return c.json({
          ok: false,
          reason: 'no_events_for_snapshot',
          tick,
          inputHash,
          checked: 0,
          mismatches: [],
          insufficient: [],
        }, 404)
      }

      const traceIds = [...new Set(events.map(e => e.traceId))]

      // ---- 真实事实 #1：哪些 trace 真的落库了 memory_version（S8 的唯一依据） ----
      const versionRows = await db
        .select({ traceId: schema.v9MemoryTxs.traceId })
        .from(schema.v9MemoryVersions)
        .innerJoin(schema.v9MemoryTxs, eq(schema.v9MemoryVersions.memoryTxId, schema.v9MemoryTxs.id))
        .where(inArray(schema.v9MemoryTxs.traceId, traceIds))
      const tracesWithMemoryVersion = new Set(versionRows.map(r => r.traceId))

      // ---- 真实事实 #2：持久化的 v6 内生快照（用于复算 w_max_*） ----
      const pgcRows = await db
        .select({
          traceId: schema.v9PgcStates.traceId,
          v6State: schema.v9PgcStates.v6State,
        })
        .from(schema.v9PgcStates)
        .where(inArray(schema.v9PgcStates.traceId, traceIds))

      const mismatches: ReplayMismatch[] = []
      const insufficient: ReplayInsufficient[] = []
      const observedNodes: string[] = []

      for (const event of events) {
        const hasMemoryVersion = tracesWithMemoryVersion.has(event.traceId)

        if (event.coreStateNode == null) {
          // 旧行：缺记录点。既不判一致、也不判漂移 —— 如实报"快照不足"。
          insufficient.push({
            kind: 'missing_core_state_node',
            eventId: event.eventId,
            traceId: event.traceId,
            missing: ['core_state_node'],
          })
          continue
        }

        observedNodes.push(event.coreStateNode)

        const recomputed = deriveCoreStateNode(event.topic, { hasMemoryVersion })
        if (recomputed !== event.coreStateNode) {
          mismatches.push({
            kind: 'core_state_node_mismatch',
            eventId: event.eventId,
            traceId: event.traceId,
            topic: event.topic,
            recorded: event.coreStateNode,
            recomputed,
          })
        }

        // §4.3：`memory_version_id !== null` 与真实落库必须一一对应。
        if (event.coreStateNode === 'S8' && !hasMemoryVersion) {
          mismatches.push({
            kind: 's8_without_memory_version',
            eventId: event.eventId,
            traceId: event.traceId,
            topic: event.topic,
            recorded: 'S8',
            recomputed: 'S6',
          })
        }
        if (event.coreStateNode === 'S6' && hasMemoryVersion) {
          mismatches.push({
            kind: 's6_with_memory_version',
            eventId: event.eventId,
            traceId: event.traceId,
            topic: event.topic,
            recorded: 'S6',
            recomputed: 'S8',
          })
        }
      }

      // ---- 复算 §4.3 点名的 w_max_*：输入只取持久化的 tau 与 s.f，不做二次变换 ----
      const observedCommitReasons: string[] = []
      for (const row of pgcRows) {
        const v6 = row.v6State as PersistedV6State | null
        if (!v6 || typeof v6.tau !== 'string' || typeof v6.s?.f !== 'number') {
          insufficient.push({
            kind: 'missing_v6_snapshot',
            traceId: row.traceId,
            missing: ['pgc_states.v6_state.tau', 'pgc_states.v6_state.s.f'],
          })
          continue
        }

        observedCommitReasons.push(v6.commit_reason)

        if (!(COMMIT_REASON_CHAIN as readonly string[]).includes(v6.commit_reason)) {
          mismatches.push({
            kind: 'commit_reason_outside_fixed_chain',
            traceId: row.traceId,
            recorded: v6.commit_reason,
          })
        }

        const recomputedBounds = computeV6WMaxBounds(v6.tau, PGC_V6_PARAMS_CASE4, v6.s.f)
        if (Math.abs(recomputedBounds.w_max_global - v6.w_max_global) > FLOAT_EPSILON) {
          mismatches.push({
            kind: 'w_max_global_drift',
            traceId: row.traceId,
            recorded: v6.w_max_global,
            recomputed: recomputedBounds.w_max_global,
          })
        }
        if (typeof recomputedBounds.w_max_at_f === 'number'
          && Math.abs(recomputedBounds.w_max_at_f - v6.w_max_at_f) > FLOAT_EPSILON) {
          mismatches.push({
            kind: 'w_max_at_f_drift',
            traceId: row.traceId,
            recorded: v6.w_max_at_f,
            recomputed: recomputedBounds.w_max_at_f,
          })
        }
      }

      const payload = {
        tick,
        inputHash,
        checked: events.length,
        coreStateNodes: observedNodes,
        commitReasons: observedCommitReasons,
        mismatches,
        insufficient,
      }

      if (mismatches.length > 0)
        return c.json({ ok: false, reason: 'mismatch', ...payload })

      if (insufficient.length > 0)
        return c.json({ ok: false, reason: 'insufficient_input_snapshot', ...payload })

      return c.json({ ok: true, ...payload })
    })
}
