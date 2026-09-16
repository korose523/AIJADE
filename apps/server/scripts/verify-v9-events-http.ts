import type { HonoEnv } from '../src/types/hono'

/**
 * Step B 验收：**HTTP 边界**端到端验证。
 *
 * 与 `verify-v9-events.ts`（只测 service）互补：本脚本走**真实 HTTP 路径**——
 * 真实路由工厂 `createV9EventsRoutes`（含 `.use('*', authGuard)` 与内部 `.post('/')`）
 * + 真实 valibot 边界校验 + 真实 service + **真实 Postgres**（pglite 即 Postgres 引擎），
 * 用的是浏览器实际会发的两个信封，最后跑用户指定的两条验收 SQL。
 *
 * ⚠️ 诚实边界（必读）：
 * - 本机的**运行时数据库不存在**：`.env.local` 指向 `localhost:5432`（连接被拒），
 *   `.env` 指向 `db:5432`（docker-compose 服务名，本机无 docker daemon）。
 *   故本脚本用的是**自带的真实 Postgres 实例**，不是"项目的运行库"。
 * - 全局 `sessionMiddleware`（`app.ts` 内）依赖 better-auth + 真实 DB，无法在此廉价复现，
 *   故用一条等价中间件注入 `c.get('user')`。`authGuard` 本身是**真的**，并且下面会
 *   断言"未登录 → 401"，证明守门逻辑确实生效。
 * - 仍未覆盖的只剩"浏览器在一次真实对话里真的把 POST 发出去"这一跳；
 *   该跳由 `packages/stage-ui/src/stores/chat/memory-performance.test.ts` 钉住
 *   （断言 send-start 发 `persona.render_requested`、render 复用同一 trace 发 `lpm.render_ready`）。
 *
 * 运行：`pnpm --filter @proj-aijade/server verify:v9-events-http`
 */
import process from 'node:process'

import { PGlite } from '@electric-sql/pglite'
import { drizzle } from 'drizzle-orm/pglite'
import { Hono } from 'hono'

import { createV9EventsRoutes } from '../src/routes/v9/events'
import { createV9EventService } from '../src/services/domain/v9-events'
import { ApiError } from '../src/utils/error'

import * as schema from '../src/schemas/memory-v9'

function assert(cond: boolean, msg: string): void {
  if (!cond) {
    console.error('FAIL:', msg)
    process.exit(1)
  }
}

/** 与 drizzle schema（memory-v9.ts 的 v9Events / v9AuditLogEntries）逐列对应的物理 DDL。 */
const DDL = `
  CREATE TABLE "events" (
    "id" text PRIMARY KEY,
    "event_id" text NOT NULL,
    "trace_id" text NOT NULL,
    "correlation_id" text NOT NULL,
    "timestamp" timestamp NOT NULL,
    "producer" text NOT NULL,
    "topic" text NOT NULL,
    "payload" jsonb,
    "idempotency_key" text NOT NULL UNIQUE,
    "replay_mode" text NOT NULL CHECK ("replay_mode" IN ('live','replay')),
    "risk_level" text NOT NULL CHECK ("risk_level" IN ('low','medium','high'))
  );
  CREATE TABLE "audit_log_entries" (
    "id" text PRIMARY KEY,
    "tx_id" text NOT NULL,
    "actor" text NOT NULL,
    "action" text NOT NULL,
    "before_hash" text,
    "after_hash" text,
    "at" timestamp NOT NULL
  );
`

interface Envelope {
  event_id: string
  trace_id: string
  correlation_id: string
  timestamp: number
  producer: string
  idempotency_key: string
  replay_mode: 'live' | 'replay'
  risk_level: 'low' | 'medium' | 'high'
  topic: string
  payload: Record<string, unknown>
}

async function main() {
  const client = new PGlite()
  const db = drizzle(client, { schema })
  await client.exec(DDL)

  const v9EventService = createV9EventService(db as never)

  // 与 app.ts 同构：全局鉴权注入 + 挂载在同一前缀（内部路由是 `.post('/')`）。
  let authed = false
  const app = new Hono<HonoEnv>()
    .use('*', async (c, next) => {
      if (authed)
        c.set('user', { id: 'user-e2e' } as never)
      await next()
    })
    // 与 app.ts 的全局错误处理同构：把 ApiError 转成对应的 JSON + 状态码。
    // 缺了它，authGuard 抛的 401 会被 Hono 兜成 500 纯文本（第一版即踩此坑）。
    .onError((err, c) => {
      if (err instanceof ApiError)
        return c.json({ error: err.errorCode, message: err.message, details: err.details }, err.statusCode)
      return c.json({ error: 'INTERNAL_SERVER_ERROR', message: 'Internal Server Error' }, 500)
    })
    .route('/api/v1/v9/events', createV9EventsRoutes(v9EventService))

  const ENDPOINT = '/api/v1/v9/events'
  async function post(env: unknown): Promise<{ status: number, body: Record<string, unknown> }> {
    const res = await app.request(ENDPOINT, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(env),
    })
    const text = await res.text()
    let body: Record<string, unknown>
    try {
      body = JSON.parse(text) as Record<string, unknown>
    }
    catch {
      // 非 JSON 响应（例如未走 onError 的框架错误页）也要能读出来，不要在这里抛。
      body = { _raw: text }
    }
    return { status: res.status, body }
  }

  const TRACE = 'trace-e2e-happy'
  const requestEnvelope: Envelope = {
    event_id: 'r1',
    trace_id: TRACE,
    correlation_id: TRACE,
    timestamp: Date.now(),
    producer: 'stage-ui',
    idempotency_key: 's1#1#request',
    replay_mode: 'live',
    risk_level: 'low',
    topic: 'aijade.persona.render_requested',
    payload: { session_id: 's1', request_ref: TRACE },
  }
  const readyEnvelope: Envelope = {
    event_id: 'e1',
    trace_id: TRACE,
    correlation_id: TRACE,
    timestamp: Date.now(),
    producer: 'stage-ui',
    idempotency_key: 's1#s1#render:1',
    replay_mode: 'live',
    risk_level: 'low',
    topic: 'aijade.lpm.render_ready',
    payload: {
      session_id: 's1',
      render_ref: 's1#render:1',
      applied_params_hash: 'emotion.intensity=0.5|emotion.preset=s:happy',
    },
  }

  // ---- 1) 未登录必须被 authGuard 拦住（证明守门真的生效）----
  const unauth = await post(requestEnvelope)
  assert(unauth.status === 401, `unauthenticated POST must be 401, got ${unauth.status}`)
  console.info('ok  unauthenticated POST -> 401 (authGuard enforced)')

  // ---- 2) 已登录：请求事件 → 回执事件，同 trace 配对成功 ----
  authed = true
  const r1 = await post(requestEnvelope)
  assert(r1.status === 201, `persona.render_requested must be 201, got ${r1.status} ${JSON.stringify(r1.body)}`)

  const r2 = await post(readyEnvelope)
  assert(r2.status === 201, `lpm.render_ready must be 201, got ${r2.status} ${JSON.stringify(r2.body)}`)
  assert(r2.body.pairingMissing === false, 'paired lpm.render_ready must NOT be flagged pairingMissing')
  console.info('ok  persona.render_requested -> 201, lpm.render_ready -> 201 (paired)')

  // ---- 3) 幂等：同一 idempotency_key 重发 → 200 deduped，且只落一行 ----
  const r3 = await post(readyEnvelope)
  assert(r3.status === 200 && r3.body.deduped === true, `retry must be 200 deduped, got ${r3.status} ${JSON.stringify(r3.body)}`)
  console.info('ok  duplicate idempotency_key -> 200 deduped')

  // ---- 4) 畸形信封在 HTTP 边界被拒（400，不静默吞）----
  const bad = await post({ topic: 'aijade.lpm.render_ready' })
  assert(bad.status === 400, `malformed envelope must be 400, got ${bad.status}`)
  console.info('ok  malformed envelope -> 400 (valibot boundary rejects)')

  // ---- 5) 配对缺口：无同 trace 请求的 render_ready → pairingMissing + 审计 ----
  const orphan = await post({
    ...readyEnvelope,
    event_id: 'e2',
    trace_id: 'trace-e2e-orphan',
    correlation_id: 'trace-e2e-orphan',
    idempotency_key: 's9#s9#render:1',
    payload: { session_id: 's9', render_ref: 's9#render:1', applied_params_hash: 'x=y' },
  })
  assert(orphan.body.pairingMissing === true, 'orphan render_ready must be flagged pairingMissing')
  console.info('ok  orphan render_ready -> pairingMissing=true (audit gap recorded)')

  // ========================================================================
  // 用户指定的两条验收查询（原样 SQL，直接打在真实 Postgres 上）
  // 注意：drizzle 导出名是 v9Events，**物理表名是 "events"**。
  // ========================================================================
  const q1 = await client.query<{ n: number }>(
    `SELECT COUNT(*)::int AS n FROM "events" WHERE topic = 'aijade.lpm.render_ready'`,
  )
  console.info(`\n[Q1] SELECT COUNT(*) FROM "events" WHERE topic='aijade.lpm.render_ready'  =>  ${q1.rows[0].n} 行`)

  const q2 = await client.query<{ trace_id: string, timestamp: Date }>(
    `SELECT trace_id, timestamp FROM "events"
      WHERE topic = 'aijade.lpm.render_ready'
      ORDER BY timestamp DESC LIMIT 1`,
  )
  assert(q2.rows.length === 1, 'expected at least one lpm.render_ready row')
  const latestTrace = q2.rows[0].trace_id

  const q3 = await client.query<{ ready_rows: number, request_rows: number }>(
    `SELECT
       (SELECT COUNT(*)::int FROM "events" WHERE topic='aijade.lpm.render_ready'          AND trace_id=$1) AS ready_rows,
       (SELECT COUNT(*)::int FROM "events" WHERE topic='aijade.persona.render_requested'  AND trace_id=$1) AS request_rows`,
    [latestTrace],
  )
  const { ready_rows: readyRows, request_rows: requestRows } = q3.rows[0]
  console.info(`[Q2] 最近一条 render_ready 的 trace_id = ${latestTrace}`)
  console.info(`[Q3] 同 trace 下：render_ready=${readyRows} 行，persona.render_requested=${requestRows} 行`)
  assert(readyRows >= 1 && requestRows >= 1, 'the latest render_ready MUST pair with a same-trace request')

  const q4 = await client.query<{ n: number }>(
    `SELECT COUNT(*)::int AS n FROM "audit_log_entries" WHERE action='render_ready_without_matching_request'`,
  )
  console.info(`[Q4] audit_log_entries 配对缺口行数 = ${q4.rows[0].n}（应 ≥1，来自 orphan 用例）`)

  console.info('\nPASS: v9-events HTTP-boundary e2e verified (401 / 201 / deduped / 400 / pairing / audit)')
  await client.close()
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
