import process from 'node:process'

/**
 * `render_traces` 投影的离线回填 CLI（v10 §6.3 / §12.1）。
 *
 * 用途：把历史上已经写入 `events`、但在投影表里**没有**对应行的渲染轨迹
 * （`persona.render_requested` + `lpm.render_ready` 配对）补进 `render_traces`，
 * 使"学习 B 的轨迹引用"不会把一段真实发生过的渲染误判为"引用不存在"。
 *
 * 为什么用 drizzle（而不是 `pg.Client` 直连，像 `accept-v9-render-loop.ts`）：
 * 回填逻辑住在 `src/services/domain/render-trace-backfill.ts`，走 drizzle 之后
 * **PGlite 与真实 PostgreSQL 是同一条代码路径**——同一个函数既能被 PGlite 单测
 * （`render-trace-backfill.test.ts`，6 例）真实覆盖，也能在真实库上跑，不存在
 * "测试跑的是 A 实现、线上跑的是 B 实现"的漂移。
 *
 * 诚实边界（2026-09-17 实测更新）：
 * - **回填逻辑已双向验证**：(a) PGlite 单测 `render-trace-backfill.test.ts`（6 例）覆盖规划与幂等；
 *   (b) `scripts/verify-render-trace-backfill.ts` 在**真实 PostgreSQL** 上跑通 20 条断言
 *   （事务内执行后 rollback，零持久写入）—— 已实测覆盖部分唯一索引冲突、jsonb 读回形状、
 *   身份链刻写、以及"缺回执 / 身份矛盾一律不造行"。
 * - **本 CLI 自身在本机只验到"连不上时的退出码与凭据脱敏"**：`apply:env` 读 `.env.local`，
 *   其中 `DATABASE_URL` 指向 `localhost:5432`，而本机该端口**未监听**（实测 `nc -z` 关闭）。
 *   真正可用的库是 docker 的 `proj-airi-server-db-1`，宿主端口 **5435**。要对真实库跑本 CLI，
 *   请显式覆盖连接串：
 *   `DATABASE_URL=postgresql://...@localhost:5435/postgres pnpm --filter @proj-aijade/server backfill:v9-render-traces -- --dry-run`
 * - 脚本**不会自动迁移**。若库缺 `render_traces` 表或 `events.core_state_node` 列，
 *   报错信息会直接暴露；请先 `pnpm --filter @proj-aijade/server db:push` 或让服务端
 *   `migrateDatabase` 跑完（注意：新增的 `0023_core_state_node.sql` 需要重建
 *   `@proj-aijade/server-schema` 才会进入运行时迁移产物）。
 *
 * 运行：
 * - 干跑（只规划、不落库）：`pnpm --filter @proj-aijade/server backfill:v9-render-traces -- --dry-run`
 * - 真回填：`pnpm --filter @proj-aijade/server backfill:v9-render-traces`
 */

const EXIT = {
  ok: 0,
  missingDatabaseUrl: 2,
  connectOrQueryError: 3,
  unexpected: 4,
} as const

/** 只暴露 host/db/path，避免把凭据打进日志。 */
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
  const dryRun = process.argv.includes('--dry-run')
  const connectionString = process.env.DATABASE_URL

  if (!connectionString) {
    console.error('[backfill:render-traces] DATABASE_URL is not set; nothing to do.')
    return EXIT.missingDatabaseUrl
  }

  const { createDrizzle } = await import('../src/libs/db')
  const { parseEnv } = await import('../src/libs/env')
  const { runRenderTraceBackfill } = await import('../src/services/domain/render-trace-backfill')

  const runtimeEnv = parseEnv(process.env)
  const { db, pool } = createDrizzle(runtimeEnv)

  try {
    await db.execute('SELECT 1')
  }
  catch (error) {
    console.error(`[backfill:render-traces] cannot connect to ${describeTarget(connectionString)}:`, error)
    await pool.end()
    return EXIT.connectOrQueryError
  }

  console.info(`[backfill:render-traces] target=${describeTarget(connectionString)} dryRun=${dryRun}`)

  try {
    const report = await runRenderTraceBackfill(db, { dryRun })
    console.info(`[backfill:render-traces] scanned events: ${report.scannedEvents}`)
    console.info(`[backfill:render-traces] planned projection rows: ${report.plannedRows}`)
    if (dryRun) {
      console.info('[backfill:render-traces] dry-run: nothing written')
    }
    else {
      console.info(`[backfill:render-traces] inserted: ${report.inserted}`)
      console.info(`[backfill:render-traces] skipped (already present): ${report.skippedExisting}`)
      console.info(`[backfill:render-traces] skipped (unique-index conflict): ${report.skippedConflict}`)
    }
    if (report.incomplete.length > 0) {
      console.warn(`[backfill:render-traces] incomplete traces (no projection fabricated): ${report.incomplete.length}`)
      for (const row of report.incomplete.slice(0, 20))
        console.warn(`  - ${row.traceId}: ${row.reason}`)
    }
    if (report.conflicts.length > 0) {
      console.warn(`[backfill:render-traces] conflicting traces (skipped): ${report.conflicts.length}`)
      for (const row of report.conflicts.slice(0, 20))
        console.warn(`  - ${row.traceId}: ${row.reason}`)
    }
    return EXIT.ok
  }
  catch (error) {
    console.error('[backfill:render-traces] backfill failed:', error)
    return EXIT.connectOrQueryError
  }
  finally {
    await pool.end()
  }
}

main()
  .then(code => process.exit(code))
  .catch((error) => {
    console.error('[backfill:render-traces] unexpected error:', error)
    process.exit(EXIT.unexpected)
  })
