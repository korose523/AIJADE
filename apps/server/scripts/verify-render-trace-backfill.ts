import process from 'node:process'

/**
 * `render_traces` 离线回填的**真实 PostgreSQL** 验收（v10 §6.3 / §12.1）。
 *
 * ## 为什么需要它（单测覆盖不到什么）
 *
 * `render-trace-backfill.test.ts` 跑在 PGlite 上，验的是**规划逻辑与幂等语义**。
 * 但真实 PostgreSQL 上还有三件事它验不了：
 * 1. `render_traces` 上那条 **部分唯一索引**（`render_ref` WHERE NOT NULL）的真实冲突行为；
 * 2. `events.payload` 是 `jsonb` 时 drizzle 读回的形状（PGlite 的 jsonb 实现与之不同）；
 * 3. 迁移产物是否真的在该库里建出了回填所需的列（例如 `events.core_state_node`）。
 *
 * ## 安全性：全程一个事务，最后 rollback
 *
 * 本脚本**不向目标库写入任何持久数据**：所有 INSERT 都在一个 `db.transaction` 里完成，
 * 断言跑完后抛哨兵错误触发 rollback。因此它可以对着开发库直接跑。
 * 这也是它比"建临时库"更合适的原因 —— 临时库需要 CREATE DATABASE 权限，
 * 在托管型 PostgreSQL 上没有，而在事务里跑随处可用。
 *
 * ## 运行
 * `DATABASE_URL=... pnpm --filter @proj-aijade/server verify:v9-render-traces`
 *
 * 退出码：0 全通过 / 2 缺 DATABASE_URL / 3 连不上或断言失败 / 4 意外错误。
 */

const EXIT = {
  ok: 0,
  missingDatabaseUrl: 2,
  failed: 3,
  unexpected: 4,
} as const

let failures = 0

function check(ok: boolean, msg: string): void {
  if (ok) {
    console.info(`ok   ${msg}`)
  }
  else {
    failures++
    console.error(`FAIL ${msg}`)
  }
}

/** 只暴露 host/port/db，避免把凭据打进日志。 */
function describeTarget(connectionString: string): string {
  try {
    const url = new URL(connectionString)
    return `${url.hostname}${url.port ? `:${url.port}` : ''}${url.pathname}`
  }
  catch {
    return '(unparseable connection string)'
  }
}

/** rollback 哨兵：不是错误，是主动回退的信号。 */
const ROLLBACK = Symbol('rollback')

interface InsertEventInput {
  eventId: string
  traceId: string
  sessionId: string
  topic: string
  payload: Record<string, unknown>
  timestampMs: number
}

async function main(): Promise<number> {
  const connectionString = process.env.DATABASE_URL
  if (!connectionString) {
    console.error('[verify:render-traces] DATABASE_URL is not set; nothing to verify.')
    return EXIT.missingDatabaseUrl
  }

  const { createDrizzle } = await import('../src/libs/db')
  const { runRenderTraceBackfill } = await import('../src/services/domain/render-trace-backfill')
  const { sql } = await import('drizzle-orm')

  // 刻意**不走** `parseEnv`：它要求完整运行环境（`REDIS_URL`、`BETTER_AUTH_*` …），
  // 对一条只碰 `events` / `render_traces` 的验收脚本是过重的耦合 —— 缺一个无关的键
  // 就会在连库之前先抛 ValiError。这里只给 `createDrizzle` 它真正需要的那几个池参数。
  const { db, pool } = createDrizzle({
    DATABASE_URL: connectionString,
    DB_POOL_MAX: 2,
    DB_POOL_IDLE_TIMEOUT_MS: 5_000,
    DB_POOL_CONNECTION_TIMEOUT_MS: 5_000,
    DB_POOL_KEEPALIVE_INITIAL_DELAY_MS: 1_000,
  })
  const stamp = Date.now()

  // 三个互不相同的 trace，各自验一条不变量：
  //   A = 请求 + 回执齐全       → 必须被回填成 1 行
  //   B = 只有请求（缺回执）    → 必须进 incomplete，且**不**造行
  //   C = 请求/回执 session 不一致 → 必须进 conflicts，且**不**造行
  const traceA = `verify-backfill-a-${stamp}`
  const traceB = `verify-backfill-b-${stamp}`
  const traceC = `verify-backfill-c-${stamp}`
  const sessionA = `verify-backfill-session-a-${stamp}`

  function event(input: InsertEventInput) {
    return sql`
      INSERT INTO "events" (
        "id", "event_id", "trace_id", "correlation_id", "timestamp", "producer",
        "origin_device", "privacy_level", "topic", "payload",
        "idempotency_key", "replay_mode", "risk_level"
      ) VALUES (
        ${`verify-evt-${input.eventId}`}, ${input.eventId}, ${input.traceId}, ${input.traceId},
        CAST(${new Date(input.timestampMs).toISOString()} AS timestamp),
        'verify-backfill', 'test', 1, ${input.topic},
        CAST(${JSON.stringify(input.payload)} AS jsonb),
        ${`verify-idem-${input.eventId}`}, 'live', 'low'
      )
    `
  }

  async function countTraces(tx: unknown, traceId: string): Promise<number> {
    const res = await (tx as { execute: (q: unknown) => Promise<{ rows: { n: number }[] }> })
      .execute(sql`SELECT COUNT(*)::int AS n FROM "render_traces" WHERE "trace_id" = ${traceId}`)
    return res.rows[0].n
  }

  try {
    console.info(`[verify:render-traces] target=${describeTarget(connectionString)} (all writes rolled back)`)

    try {
      await db.transaction(async (tx) => {
        // ---- 种下三个 trace 的事件 ----
        await tx.execute(event({
          eventId: 'a-req',
          traceId: traceA,
          sessionId: sessionA,
          topic: 'aijade.persona.render_requested',
          payload: { session_id: sessionA, persona_snapshot_ref: 'snap-a', intent_ref: 'identity-a' },
          timestampMs: stamp - 3000,
        }))
        await tx.execute(event({
          eventId: 'a-ready',
          traceId: traceA,
          sessionId: sessionA,
          topic: 'aijade.lpm.render_ready',
          // 关键：回执身份必须与请求身份同源（v10 §6 身份链）——`render_ref` 等于 `intent_ref`。
          payload: {
            session_id: sessionA,
            render_ref: 'identity-a',
            applied_params_hash: 'applied-a',
            asset_version_hash: 'asset-a',
          },
          timestampMs: stamp - 2000,
        }))

        await tx.execute(event({
          eventId: 'b-req',
          traceId: traceB,
          sessionId: sessionA,
          topic: 'aijade.persona.render_requested',
          payload: { session_id: sessionA, persona_snapshot_ref: 'snap-b', intent_ref: 'identity-b' },
          timestampMs: stamp - 1000,
        }))

        await tx.execute(event({
          eventId: 'c-req',
          traceId: traceC,
          sessionId: sessionA,
          topic: 'aijade.persona.render_requested',
          payload: { session_id: sessionA, persona_snapshot_ref: 'snap-c', intent_ref: 'identity-c' },
          timestampMs: stamp - 1000,
        }))
        await tx.execute(event({
          eventId: 'c-ready',
          traceId: traceC,
          sessionId: 'a-different-session',
          topic: 'aijade.lpm.render_ready',
          payload: {
            session_id: 'a-different-session',
            render_ref: 'identity-c',
            applied_params_hash: 'applied-c',
            asset_version_hash: 'asset-c',
          },
          timestampMs: stamp - 500,
        }))

        // ---- 干跑：只规划，不落库 ----
        const dry = await runRenderTraceBackfill(tx as never, { dryRun: true })
        check(dry.plannedRows >= 1, `dry-run plans the paired trace (planned=${dry.plannedRows})`)
        check(dry.inserted === 0, `dry-run writes nothing (inserted=${dry.inserted})`)
        check(await countTraces(tx, traceA) === 0, 'dry-run left render_traces untouched')
        check(
          dry.incomplete.some(i => i.traceId === traceB),
          'request-without-receipt is reported incomplete (no projection fabricated)',
        )
        check(
          dry.conflicts.some(c => c.traceId === traceC),
          'session_id mismatch between request and receipt is reported as a conflict',
        )

        // ---- 真回填 ----
        const first = await runRenderTraceBackfill(tx as never)
        check(first.inserted >= 1, `first real run inserts the projection (inserted=${first.inserted})`)
        check(await countTraces(tx, traceA) === 1, 'paired trace now has exactly one render_traces row')
        check(await countTraces(tx, traceB) === 0, 'incomplete trace did NOT get a fabricated row')
        check(await countTraces(tx, traceC) === 0, 'conflicting trace did NOT get a row')

        // ---- 幂等性：第二次必须一行不入 ----
        const second = await runRenderTraceBackfill(tx as never)
        check(second.inserted === 0, `second run inserts nothing (inserted=${second.inserted})`)
        check(second.skippedExisting >= 1, `second run recognises the existing projection (skippedExisting=${second.skippedExisting})`)
        check(await countTraces(tx, traceA) === 1, 'idempotent: still exactly one row for the paired trace')

        // ---- 落库内容：身份链必须来自两个事件，且 render_ref === intent_ref ----
        const row = await tx.execute(sql`
          SELECT "session_id", "intent_ref", "render_ref", "applied_params_hash",
                 "asset_version_hash", "persona_snapshot_ref", "event_id"
          FROM "render_traces" WHERE "trace_id" = ${traceA}
        `) as { rows: Record<string, string | null>[] }

        const r = row.rows[0]
        check(Boolean(r), 'projection row is readable back')
        if (r) {
          check(r.intent_ref === 'identity-a', `intent_ref carried from the request (got ${r.intent_ref})`)
          check(r.render_ref === 'identity-a', `render_ref carried from the receipt (got ${r.render_ref})`)
          check(r.intent_ref === r.render_ref, 'identity chain holds: intent_ref === render_ref (v10 §6)')
          check(r.persona_snapshot_ref === 'snap-a', `persona_snapshot_ref carried (got ${r.persona_snapshot_ref})`)
          check(r.applied_params_hash === 'applied-a', `applied_params_hash carried (got ${r.applied_params_hash})`)
          check(r.asset_version_hash === 'asset-a', `asset_version_hash carried (got ${r.asset_version_hash})`)
          check(r.session_id === sessionA, `session_id carried (got ${r.session_id})`)
        }

        throw ROLLBACK
      })
    }
    catch (error) {
      if (error !== ROLLBACK)
        throw error
    }

    if (failures > 0) {
      console.error(`\nFAIL: ${failures} render-trace backfill assertion(s) failed`)
      return EXIT.failed
    }
    console.info('\nPASS: render_trace offline backfill on real PostgreSQL (idempotent, no fabrication, rolled back)')
    return EXIT.ok
  }
  catch (error) {
    console.error('[verify:render-traces] failed:', error)
    return EXIT.failed
  }
  finally {
    await pool.end()
  }
}

main()
  .then(code => process.exit(code))
  .catch((error) => {
    console.error('[verify:render-traces] unexpected error:', error)
    process.exit(EXIT.unexpected)
  })
