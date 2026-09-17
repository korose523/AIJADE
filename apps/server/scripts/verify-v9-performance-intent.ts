import process from 'node:process'

/**
 * 真实 PostgreSQL 上的 `PerformanceIntent` 派生验收。
 *
 * ## 为什么需要它（单测覆盖不到什么）
 *
 * `v9-performance-intent.test.ts` 跑在 PGlite + **手写 DDL** 上，验的是派生逻辑。
 * 真实库上还有三件它验不了：
 * 1. 迁移产物是否真的建出了 `persona_snapshots` / `performance_intents` 的**真实列与约束**
 *    （手写 DDL 与迁移漂移正是本项目反复踩的坑）；
 * 2. `intent` 是 `jsonb` 时 drizzle 读回的形状是否仍是内核 `PerformanceIntent`；
 * 3. 落库的 `persona_snapshot_ref` 是否**真的外键指向**一张存在的快照行 ——
 *    单测只比对字符串，不会发现"引用了一个不存在的 id"。
 *
 * ## 安全性：全程一个事务，最后 rollback
 *
 * 不向目标库写入任何持久数据。断言跑完后抛哨兵触发 rollback，故可对着开发库直接跑。
 *
 * ## 运行
 * `DATABASE_URL=... pnpm --filter @proj-aijade/server verify:v9-performance-intent`
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

async function main(): Promise<number> {
  const connectionString = process.env.DATABASE_URL
  if (!connectionString) {
    console.error('[verify:intent] DATABASE_URL is not set; nothing to verify.')
    return EXIT.missingDatabaseUrl
  }

  const { createDrizzle } = await import('../src/libs/db')
  const { createV9PerformanceIntentService, NoEvidenceError } = await import('../src/services/domain/v9-performance-intent')
  const { validatePerformanceIntent } = await import('@proj-aijade/memory-biomimetic')
  const { sql } = await import('drizzle-orm')

  // 刻意不走 `parseEnv`：它要求完整运行环境（REDIS_URL、BETTER_AUTH_* …），
  // 对一条只碰四张表的验收脚本是过重的耦合。
  const { db, pool } = createDrizzle({
    DATABASE_URL: connectionString,
    DB_POOL_MAX: 2,
    DB_POOL_IDLE_TIMEOUT_MS: 5_000,
    DB_POOL_CONNECTION_TIMEOUT_MS: 5_000,
    DB_POOL_KEEPALIVE_INITIAL_DELAY_MS: 1_000,
  })

  const stamp = Date.now()
  const sessionId = `verify-intent-session-${stamp}`
  const emptySessionId = `verify-intent-empty-${stamp}`
  const userId = `verify-intent-user-${stamp}`

  try {
    console.info(`[verify:intent] target=${describeTarget(connectionString)} (all writes rolled back)`)

    try {
      await db.transaction(async (txAny) => {
        // 服务接受一个 drizzle `Database`；事务对象形状兼容，按既有脚本的口径转型。
        const tx = txAny as unknown as Parameters<typeof createV9PerformanceIntentService>[0]['db']
        const svc = createV9PerformanceIntentService({ db: tx })

        // ---- 种一条证据（pack + chunk）----
        const packId = `verify-intent-pack-${stamp}`
        await txAny.execute(sql`
          INSERT INTO "evidence_packs" ("id", "session_id", "source", "created_at")
          VALUES (${packId}, ${sessionId}, 'chat', NOW())
        `)
        await txAny.execute(sql`
          INSERT INTO "evidence_chunks" ("id", "pack_id", "idx", "content", "created_at")
          VALUES (${`${packId}-c0`}, ${packId}, '0', 'Is the pipeline reproducible?', NOW())
        `)

        // ---- 1. 派生 ------------------------------------------------
        const result = await svc.deriveForSession({
          userId,
          sessionId,
          deviceId: 'verify-device',
          privacyLevel: 1,
          agentId: 'verify-agent',
          userScope: `user:${userId}`,
        })

        const intent = result.intent.intent as Record<string, unknown>

        // ---- 2. 落库的是内核 PerformanceIntent，不是仿冒结构 ----
        check(
          intent.schema === 'aijade.performance_intent@1',
          `stored intent carries the kernel schema tag (got ${String(intent.schema)})`,
        )
        check(
          typeof intent.id === 'string' && intent.id.length > 0,
          `intent has a real id (got ${String(intent.id)})`,
        )
        check(intent.agentId === 'verify-agent', `intent carries agentId (got ${String(intent.agentId)})`)
        check(intent.userScope === `user:${userId}`, `intent carries userScope (got ${String(intent.userScope)})`)
        check(
          typeof intent.timeMarked === 'number' && Number.isFinite(intent.timeMarked),
          `intent.timeMarked is a finite number (got ${String(intent.timeMarked)})`,
        )
        check(
          typeof intent.duration === 'number' && Number.isFinite(intent.duration) && intent.duration >= 0,
          `intent.duration is finite and >= 0 (got ${String(intent.duration)})`,
        )

        // 旧的手搓仿冒结构有 `channels`、没有 `schema`。这一条证明它确实被换掉了。
        check(
          intent.channels === undefined,
          'the hand-rolled look-alike shape is gone (no `channels` field)',
        )

        // ---- 3. 内核校验真的通过（不是我们自己说了算）----
        const validation = validatePerformanceIntent(intent as never)
        check(validation.ok === true, `validatePerformanceIntent accepts the stored intent (${JSON.stringify(validation).slice(0, 160)})`)

        // ---- 4. 非恒真：篡改必须被检出 ----
        //    证明上一条不是在"对一个恒真校验器做断言"。
        const tampered = { ...intent, expression: { ...(intent.expression as Record<string, unknown> ?? {}), valence: 5 } }
        const tamperVerdict = validatePerformanceIntent(tampered as never)
        check(
          tamperVerdict.ok === false,
          'tampering expression.valence out of [-1,1] IS rejected (the validator is not always-true)',
        )

        // ---- 5. persona_snapshot_ref 真的指向一张存在的快照行 ----
        const snapRef = result.intent.personaSnapshotRef
        check(snapRef === result.snapshot.id, `persona_snapshot_ref equals the minted snapshot id (got ${snapRef})`)

        const snapRow = await txAny.execute(sql`
          SELECT COUNT(*)::int AS n FROM "persona_snapshots" WHERE "id" = ${snapRef}
        `) as { rows: { n: number }[] }
        check(snapRow.rows[0].n === 1, 'persona_snapshot_ref points at a row that actually exists')

        // ---- 6. 无证据 ⇒ 明确拒绝，且两表都不落库 ----
        let refused = false
        try {
          await svc.deriveForSession({
            userId,
            sessionId: emptySessionId,
            deviceId: 'verify-device',
            privacyLevel: 1,
            agentId: 'verify-agent',
            userScope: `user:${userId}`,
          })
        }
        catch (error) {
          refused = error instanceof NoEvidenceError
        }
        check(refused, 'a session with no evidence is refused with NoEvidenceError (no blank intent emitted)')

        const orphan = await txAny.execute(sql`
          SELECT
            (SELECT COUNT(*)::int FROM "persona_snapshots" WHERE "user_id" = ${userId}) AS snaps,
            (SELECT COUNT(*)::int FROM "performance_intents" WHERE "user_id" = ${userId}) AS intents
        `) as { rows: { snaps: number, intents: number }[] }
        check(
          orphan.rows[0].snaps === 1 && orphan.rows[0].intents === 1,
          `refusal wrote nothing: exactly 1 snapshot and 1 intent (got ${orphan.rows[0].snaps}/${orphan.rows[0].intents})`,
        )

        throw ROLLBACK
      })
    }
    catch (error) {
      if (error !== ROLLBACK)
        throw error
    }

    if (failures > 0) {
      console.error(`\nFAIL: ${failures} performance-intent assertion(s) failed`)
      return EXIT.failed
    }
    console.info('\nPASS: validated PerformanceIntent derivation on real PostgreSQL (kernel-shaped, tamper-detectable, rolled back)')
    return EXIT.ok
  }
  catch (error) {
    console.error('[verify:intent] failed:', error)
    return EXIT.failed
  }
  finally {
    await pool.end()
  }
}

main()
  .then(code => process.exit(code))
  .catch((error) => {
    console.error('[verify:intent] unexpected error:', error)
    process.exit(EXIT.unexpected)
  })
