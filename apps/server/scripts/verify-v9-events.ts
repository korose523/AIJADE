/**
 * 一次性可重跑的 Step B 闭环验证（不依赖 vitest / pnpm install）。
 *
 * 用内存版 Postgres（@electric-sql/pglite）跑真实 SQL，证明服务端 sink 的三条不变量：
 *   1. 幂等：同一 `idempotency_key` 重复提交 → 只落一行（deduped）。
 *   2. 配对：`lpm.render_ready` 到手时反查同 trace 的 `persona.render_requested`；
 *      缺口写入 `audit_log_entries`。
 *   3. 失败可见：畸形由路由层拦截（本脚本不覆盖路由，只覆盖 service 的真实 DB 行为）。
 *
 * 运行：`npx tsx apps/server/scripts/verify-v9-events.ts`（或 `pnpm --filter @proj-aijade/server verify:v9-events`）
 */
import process from 'node:process'

import { PGlite } from '@electric-sql/pglite'
import { and, eq } from 'drizzle-orm'
import { drizzle } from 'drizzle-orm/pglite'

import { assertSchemaMatchesDrizzle, buildMemoryV9Ddl, memoryV9Tables } from '../src/schemas/pglite-ddl'
import { createV9EventService } from '../src/services/domain/v9-events'

import * as schema from '../src/schemas/memory-v9'

function assert(cond: boolean, msg: string): void {
  if (!cond) {
    console.error('FAIL:', msg)
    process.exit(1)
  }
}

/**
 * 物理 DDL：**由 drizzle schema 生成**，不再手抄（见 `_shared/pglite-memory-schema.ts` 头注）。
 *
 * 本文件先前手抄的 DDL 是当时三份副本里**最新**的一份（已含 v9 的 8 个新列与
 * `render_traces`），另两份则否 —— 这正是"同一形状抄多份"的典型代价：正确性取决于
 * 哪一份最近被改过。改为生成后，三处共用同一真源。
 */
const DDL = buildMemoryV9Ddl()

async function main() {
  const client = new PGlite()
  const db = drizzle(client, { schema })
  await client.exec(DDL)
  await assertSchemaMatchesDrizzle(client, memoryV9Tables())

  const svc = createV9EventService(db as any)
  const trace = 'trace-1'

  // 信封的观察/传输上下文：内核信封与 HTTP 边界都要求这 5 个字段必填，故此处如实给出。
  const OBS = {
    origin_device: 'script:verify-v9-events',
    privacy_level: 1 as const,
    evidence_refs: [] as string[],
    causal_context_refs: [trace],
    risk_score: 0,
  }

  // 1) 正常闭环：同 trace 下先 request 后 ready，配对成功。
  await svc.appendEvent({
    event_id: 'r1',
    trace_id: trace,
    correlation_id: trace,
    timestamp: Date.now(),
    producer: 'stage-ui',
    ...OBS,
    idempotency_key: 's1#1#request',
    replay_mode: 'live',
    risk_level: 'low',
    topic: 'aijade.persona.render_requested',
    payload: { session_id: 's1', persona_snapshot_ref: 's1#persona', intent_ref: 's1#intent:1' },
  })
  const ready = await svc.appendEvent({
    event_id: 'e1',
    trace_id: trace,
    correlation_id: trace,
    timestamp: Date.now(),
    producer: 'stage-ui',
    ...OBS,
    idempotency_key: 's1#s1#render:1',
    replay_mode: 'live',
    risk_level: 'low',
    topic: 'aijade.lpm.render_ready',
    payload: { session_id: 's1', render_ref: 's1#render:1', applied_params_hash: 'emotion.preset=happy' },
  })
  assert(!ready.deduped, 'first lpm.render_ready should NOT be deduped')
  assert(ready.pairingMissing !== true, 'paired render_ready must NOT be flagged pairingMissing')

  // 2) 幂等：同 idempotency_key 重复提交 → deduped，且只落一行。
  const dup = await svc.appendEvent({
    event_id: 'e1b',
    trace_id: trace,
    correlation_id: trace,
    timestamp: Date.now(),
    producer: 'stage-ui',
    ...OBS,
    idempotency_key: 's1#s1#render:1',
    replay_mode: 'live',
    risk_level: 'low',
    topic: 'aijade.lpm.render_ready',
    payload: { session_id: 's1', render_ref: 's1#render:1', applied_params_hash: 'emotion.preset=happy' },
  })
  assert(dup.deduped, 'duplicate idempotency_key MUST be deduped')
  const readyRows = await db.select().from(schema.v9Events).where(eq(schema.v9Events.topic, 'aijade.lpm.render_ready'))
  assert(readyRows.length === 1, `expect exactly 1 lpm.render_ready row after dedup, got ${readyRows.length}`)

  // 3) 配对缺口：无同 trace request 的 render_ready → audit 行 + pairingMissing。
  const orphan = await svc.appendEvent({
    event_id: 'e2',
    trace_id: 'trace-orphan',
    correlation_id: 'trace-orphan',
    timestamp: Date.now(),
    producer: 'stage-ui',
    ...OBS,
    idempotency_key: 's9#s9#render:1',
    replay_mode: 'live',
    risk_level: 'low',
    topic: 'aijade.lpm.render_ready',
    payload: { session_id: 's9', render_ref: 's9#render:1', applied_params_hash: 'x=y' },
  })
  assert(orphan.pairingMissing === true, 'orphan render_ready MUST be flagged pairingMissing')
  const audit = await db.select().from(schema.v9AuditLogEntries).where(eq(schema.v9AuditLogEntries.action, 'render_ready_without_matching_request'))
  assert(audit.length >= 1, 'audit entry MUST be written for a pairing gap')

  // 反查：orphan 的 ready 必须能按 trace 找到"无 request"的事实（这就是 P4 证据链）。
  const requestsForOrphan = await db.select().from(schema.v9Events).where(and(eq(schema.v9Events.topic, 'aijade.persona.render_requested'), eq(schema.v9Events.traceId, 'trace-orphan')))
  assert(requestsForOrphan.length === 0, 'orphan trace must have zero persona.render_requested (the gap is real)')

  console.info('PASS: v9-events closed loop verified (idempotency + pairing + audit gap)')
  await client.close()
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
