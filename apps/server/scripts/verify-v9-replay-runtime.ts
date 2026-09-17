import process from 'node:process'

/**
 * 回放一致性 API 的**真实运行期数据**验收（v10 §4.3 / §11.3）。
 *
 * ## 为什么需要它（单测覆盖不到什么）
 *
 * `routes/v9/replay.test.ts` 跑在 PGlite 上，事件行是**手工塞进去的**。它证明了
 * 回放能检出篡改，却证明不了一件更基本的事：**真实运行期产出的事件，回放能不能查得到。**
 *
 * 这两件事曾经是分开的，而且真实那一半是坏的：
 * 1. 运行期持久化（`v9-runtime-store.ts`）从不写 `tick` / `causality` / `core_state_node`，
 *    而回放正是按这三列取数与比对 —— 于是真实事件按 tick 查是 **0 行**。
 * 2. §4.3 点名的 `w_max_*` 复算需要**决策当下的 v6 快照**，而内核把它映射成行时只留了
 *    `pgcStateId`，快照被丢弃 —— 于是即便查到了事件，也只能报 `insufficient_input_snapshot`。
 *
 * 本脚本对着**真实 PostgreSQL**、用**运行期实际写入的行**跑回放，逐一钉住上面两条。
 *
 * ## 安全性
 *
 * 只读为主：唯一一次写入是「篡改一条 jsonb 里的小数值」以证明漂移可检出，且在
 * `finally` 里按**原始值**原样写回，并在最后回读校验恢复一致。不新增/删除任何行。
 *
 * ## 运行
 * `DATABASE_URL=... pnpm --filter @proj-aijade/server verify:v9-replay-runtime`
 *
 * 退出码：0 全通过 / 2 缺 DATABASE_URL / 3 断言失败 / 4 意外错误 / 5 找不到运行期快照。
 */

const EXIT = {
  ok: 0,
  missingDatabaseUrl: 2,
  failed: 3,
  unexpected: 4,
  noRuntimeSnapshot: 5,
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

async function main(): Promise<number> {
  const connectionString = process.env.DATABASE_URL
  if (!connectionString) {
    console.error('[verify:v9-replay-runtime] DATABASE_URL is not set; nothing to verify.')
    return EXIT.missingDatabaseUrl
  }

  console.info(`[verify:v9-replay-runtime] target = ${describeTarget(connectionString)}`)

  const { createDrizzle } = await import('../src/libs/db')
  const { createV9ReplayRoutes } = await import('../src/routes/v9/replay')
  const { sql } = await import('drizzle-orm')
  const { Hono } = await import('hono')

  const { db, pool } = createDrizzle({
    DATABASE_URL: connectionString,
    DB_POOL_MAX: 2,
    DB_POOL_IDLE_TIMEOUT_MS: 5_000,
    DB_POOL_CONNECTION_TIMEOUT_MS: 5_000,
    DB_POOL_KEEPALIVE_INITIAL_DELAY_MS: 1_000,
  })

  const app = new Hono()
    .use('*', async (c, next) => {
      c.set('user', { id: 'verify-replay' } as never)
      await next()
    })
    .route('/api/v1/v9/replay', createV9ReplayRoutes(db as never))

  async function replay(tick: number, inputHash: string) {
    const res = await app.request('/api/v1/v9/replay', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ tick, inputHash }),
    })
    return { status: res.status, body: await res.json() as Record<string, unknown> }
  }

  // ---- 1. 找一个**真实运行期产出**的输入快照：有 tick + inputHash + core_state_node，
  //         且其 trace 的 pgc_write_plans 里有带 v6 的决策快照。 ----
  const snapshotRows = await db.execute(sql`
    SELECT e.tick::text        AS tick,
           e.causality->>'inputHash' AS input_hash,
           e.trace_id          AS trace_id,
           count(*)::text      AS event_count
    FROM "events" e
    WHERE e.tick IS NOT NULL
      AND e.causality->>'inputHash' IS NOT NULL
      AND e.core_state_node IS NOT NULL
      AND EXISTS (
        SELECT 1 FROM "pgc_write_plans" w
        WHERE w.trace_id = e.trace_id
          AND w.write_plan::text LIKE '%pgcStateSnapshot%'
      )
    GROUP BY 1, 2, 3
    ORDER BY count(*) DESC
    LIMIT 1
  `) as unknown as { rows: { tick: string, input_hash: string, trace_id: string, event_count: string }[] }

  const snapshot = snapshotRows.rows[0]
  if (!snapshot) {
    console.error('[verify:v9-replay-runtime] no runtime-produced snapshot found in this database.')
    console.error('  A snapshot needs: events.tick + events.causality.inputHash + events.core_state_node,')
    console.error('  and a pgc_write_plans row for the same trace carrying pgcStateSnapshot.v6.')
    console.error('  Produce one by running the worker over a video observation (see verify-v9-promotion-worker.ts).')
    await pool.end()
    return EXIT.noRuntimeSnapshot
  }

  const tick = Number(snapshot.tick)
  const inputHash = snapshot.input_hash
  const traceId = snapshot.trace_id
  console.info(`[verify:v9-replay-runtime] snapshot: tick=${tick} trace=${traceId} recordedEvents=${snapshot.event_count}`)

  // 这一条直接钉住「运行期持久化丢了 v10 三列」那个缺陷：若不是修好了，这里根本没有快照可选。
  check(Number.isInteger(tick) && tick >= 0, `runtime events carry a persisted tick (${tick})`)
  check(snapshot.event_count !== '0', `runtime events carry causality.inputHash (${snapshot.event_count} events)`)

  // ---- 2. 正向：真实运行期数据必须回放**通过**（而非降级成 insufficient） ----
  const good = await replay(tick, inputHash)
  check(good.status === 200, `POST /api/v1/v9/replay -> 200 (got ${good.status})`)
  check(good.body.ok === true, `replay reports ok=true on real runtime data (reason=${String(good.body.reason ?? 'none')})`)
  check(good.body.reason === undefined, `no degradation reason (got ${String(good.body.reason ?? 'none')})`)

  const mismatches = (good.body.mismatches ?? []) as unknown[]
  const insufficient = (good.body.insufficient ?? []) as unknown[]
  check(mismatches.length === 0, `no mismatches (${mismatches.length})`)
  check(insufficient.length === 0, `no insufficient-input reports (${insufficient.length})`)

  const nodes = (good.body.coreStateNodes ?? []) as string[]
  const reasons = (good.body.commitReasons ?? []) as string[]
  check(nodes.length >= 3, `the snapshot covers the S3/S5/S7 chain (nodes=${JSON.stringify(nodes)})`)
  check(reasons.length >= 1, `the write-plan v6 snapshot was actually consumed (commitReasons=${JSON.stringify(reasons)})`)

  // `memory_tx.committed` 是 S6/S8（是否真实落库）的唯一记录点，必须同属这次快照。
  const committedInSnapshot = await db.execute(sql`
    SELECT count(*)::text AS n FROM "events"
    WHERE topic = 'aijade.memory_tx.committed'
      AND tick = ${tick}
      AND causality->>'inputHash' = ${inputHash}
  `) as unknown as { rows: { n: string }[] }
  check(
    committedInSnapshot.rows[0]!.n !== '0',
    'aijade.memory_tx.committed belongs to the same snapshot (so S6/S8 is replayable)',
  )

  // ---- 3. 反向：篡改一条真实行里的小数值，回放**必须**报漂移 ----
  //      （证明这个 API 在真实数据上不是恒真式，而不是只对手工测试数据敏感。）
  const target = await db.execute(sql`
    SELECT id::text AS id, write_plan::text AS write_plan
    FROM "pgc_write_plans"
    WHERE trace_id = ${traceId}
    ORDER BY created_at DESC
    LIMIT 1
  `) as unknown as { rows: { id: string, write_plan: string }[] }
  const planRow = target.rows[0]

  if (!planRow) {
    check(false, 'a pgc_write_plans row exists for the snapshot trace')
  }
  else {
    const original = planRow.write_plan
    let tampered = false
    try {
      const parsed = JSON.parse(original) as { pgcStateSnapshot?: { v6?: Record<string, unknown> } }[]
      const v6 = parsed[0]?.pgcStateSnapshot?.v6
      if (!v6 || typeof v6.w_max_global !== 'number') {
        check(false, 'the persisted v6 snapshot exposes w_max_global for tampering (as §4.3 requires)')
      }
      else {
        v6.w_max_global = (v6.w_max_global as number) + 0.5
        await db.execute(sql`
          UPDATE "pgc_write_plans" SET write_plan = ${JSON.stringify(parsed)}::jsonb WHERE id = ${planRow.id}
        `)
        tampered = true

        const bad = await replay(tick, inputHash)
        check(bad.body.ok === false, 'a tampered w_max_global makes replay fail (not ok)')
        check(bad.body.reason === 'mismatch', `the failure reason is 'mismatch' (got ${String(bad.body.reason)})`)
        const badMismatches = (bad.body.mismatches ?? []) as { kind?: string }[]
        check(
          badMismatches.some(m => m.kind === 'w_max_global_drift'),
          `the drift is attributed to w_max_global (kinds=${JSON.stringify(badMismatches.map(m => m.kind))})`,
        )
      }
    }
    finally {
      if (tampered) {
        // 按**原始值**原样写回，并回读校验，确保不留任何残留。
        await db.execute(sql`
          UPDATE "pgc_write_plans" SET write_plan = ${original}::jsonb WHERE id = ${planRow.id}
        `)
        const restored = await db.execute(sql`
          SELECT write_plan::text AS write_plan FROM "pgc_write_plans" WHERE id = ${planRow.id}
        `) as unknown as { rows: { write_plan: string }[] }
        check(restored.rows[0]?.write_plan === original, 'the tampered write_plan row was restored byte-for-byte')
      }
    }
  }

  // ---- 4. 负例：不存在的快照必须明确失败，而不是"没有漂移" ----
  const missing = await replay(999_999_999, 'no-such-input-hash')
  check(missing.status === 404, `an unknown snapshot -> 404 (got ${missing.status})`)
  check(missing.body.ok === false, 'an unknown snapshot does not report ok')

  await pool.end()

  if (failures > 0) {
    console.error(`\nFAIL: ${failures} replay assertion(s) failed`)
    return EXIT.failed
  }
  console.info('\nPASS: replay consistency verified against runtime-produced rows on real PostgreSQL')
  return EXIT.ok
}

main()
  .then(code => process.exit(code))
  .catch((error) => {
    console.error('[verify:v9-replay-runtime] unexpected error:', error)
    process.exit(EXIT.unexpected)
  })
