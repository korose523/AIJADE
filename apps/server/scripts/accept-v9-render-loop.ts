/**
 * Step B「最小闭环」**运行库验收**脚本 —— 打到真实运行库上，判定 PASS/FAIL。
 *
 * ⚠️ 诚实边界（必读，勿删）
 *
 * 本脚本由三部分组成，**验证程度不同**：
 *
 * 1. **决策逻辑**（`evaluateAcceptance`）—— **已验证**。
 *    有独立单测 `accept-v9-render-loop.test.ts`，覆盖 PASS / 三种 FAIL / WARN 分支。
 * 2. **4 条 SQL 语句与错误/脱敏工具** —— **已验证**。
 *    - SQL 与 `verify-v9-events-http.ts` 打在真实 Postgres（pglite）上的那 4 条同构：
 *      语句合法、返回形状确定。
 *    - 错误格式化 / 凭据脱敏 / JSON 组装是纯函数，单测覆盖。
 * 3. **连接真实运行库并读出真实数据** —— **未在本机验证**。
 *    本机**没有运行期数据库**：全机无 postgres 二进制、无 docker daemon、无 brew；
 *    `.env.local` 指向 `localhost:5432` 而该端口无人监听；redis 亦无。
 *    故本脚本在本机只跑通了 **参数解析 / 连接失败路径 / 退出码 / 凭据脱敏**，
 *    **从未**在一轮真实对话后读出过真实数据。**不要**据此声称端到端已活体验证。
 *
 * 因此：本脚本是"给你在能跑的机器上执行"的判定器，不是"已完成验收"的证据。
 * 真正的活体验收需要：真实 Postgres + Redis（`apps/server/src/app.ts:478` 的 redis provider
 * 在 `injeca.start()` 里带重试 `await instance.connect()`，无 Redis 服务端起不来）+ 浏览器。
 *
 * 运行：`pnpm --filter @proj-aijade/server accept:v9-render-loop`（经 `apply:env` 载入 .env.local）
 *      加 `--json` 可输出机器可读结果（stdout 只有 JSON）。
 *
 * 退出码（便于 CI 区分"配置错"与"断言不过"）：
 *   0 PASS · 1 断言 FAIL · 2 未设置 DATABASE_URL · 3 连接/查询错误 · 4 未预期异常
 */
import process from 'node:process'

import { Client } from 'pg'

/** 事件 topic 字面量单一真源 —— 只此一处出现，避免 SQL 里重复字面量而漂移。 */
export const V9_TOPICS = {
  lpmRenderReady: 'aijade.lpm.render_ready',
  personaRenderRequested: 'aijade.persona.render_requested',
} as const

/** 配对缺口的审计 action 字面量（落库只能靠它查，`pairingMissing` 不是列，只是响应体字段）。 */
export const AUDIT_ACTION_RENDER_READY_WITHOUT_MATCHING_REQUEST
  = 'render_ready_without_matching_request'

/** 退出码：分离"配置错"与"断言不过"，便于 CI 归因。 */
export const ACCEPT_EXIT = {
  pass: 0,
  fail: 1,
  missingDatabaseUrl: 2,
  connectOrQueryError: 3,
  unexpected: 4,
} as const

export interface AcceptanceInput {
  /** ① `events` 里 `topic='aijade.lpm.render_ready'` 的行数。 */
  renderReadyCount: number
  /** ② 最近一条 `render_ready` 的 `trace_id`；没有回执时为 null。 */
  latestTraceId: string | null
  /** ③ 该 trace 下 `persona.render_requested` 的行数；没有回执时为 null（无法反查）。 */
  requestCountForLatestTrace: number | null
  /** ④ `audit_log_entries` 里 `action='render_ready_without_matching_request'` 的行数。 */
  orphanAuditCount: number
}

export interface AcceptanceVerdict {
  pass: boolean
  /** 逐行输出（含判据与实际值），便于贴给他人复核。 */
  lines: string[]
  exitCode: 0 | 1
}

/**
 * 纯函数判定器。刻意与数据库访问分离，使其可被单测**真正**覆盖。
 *
 * 判据（用户拍板的"最小闭环"）：
 *   ① >= 1 且 ③ >= 1  ⇒ PASS
 * 另：④ 是**诊断信号**而非判据 —— 干净的一轮对话里它应为 0。
 */
export function evaluateAcceptance(input: AcceptanceInput): AcceptanceVerdict {
  const { renderReadyCount, latestTraceId, requestCountForLatestTrace, orphanAuditCount } = input
  const lines: string[] = [
    `① lpm.render_ready 总行数                = ${renderReadyCount}    (判据 >= 1)`,
    `② 最近一条 render_ready 的 trace_id      = ${latestTraceId ?? '(无回执)'}`,
    `③ 同 trace 的 persona.render_requested   = ${requestCountForLatestTrace ?? '(无法反查：无回执)'}    (判据 >= 1)`,
    `④ 配对缺口审计行数                        = ${orphanAuditCount}    (干净一轮应为 0)`,
  ]

  if (renderReadyCount < 1) {
    lines.push(
      'FAIL: 运行库里没有任何 lpm.render_ready。',
      '  → 浏览器那一跳没把 POST 发出去，或这轮对话根本没触发 onMessageSendStarted。',
      '  → 先查 server 日志里有没有 [v9-event-reporter] event rejected（401 鉴权 / 400 校验）。',
    )
    return { pass: false, lines, exitCode: ACCEPT_EXIT.fail }
  }

  if (requestCountForLatestTrace === null || requestCountForLatestTrace < 1) {
    lines.push(
      'FAIL: 有回执，但同 trace 找不到 persona.render_requested。',
      '  → 配对失败。先怀疑两端 trace_id 不一致（这是最小闭环里唯一靠约定维系的不变量）。',
    )
    return { pass: false, lines, exitCode: ACCEPT_EXIT.fail }
  }

  lines.push('PASS: 最小闭环成立 —— 回执存在，且能反查回同 trace 的请求。')
  if (orphanAuditCount > 0) {
    lines.push(
      `WARN: 另有 ${orphanAuditCount} 条配对缺口审计。干净的一轮对话里本不该出现；`,
      '  → 说明有渲染"忠于了不存在的意图"（例如渲染发生在 onMessageSendStarted 之前）。',
    )
  }
  return { pass: true, lines, exitCode: ACCEPT_EXIT.pass }
}

/**
 * 只读的 4 条验收 SQL。物理表名是 `"events"` / `"audit_log_entries"`（不是 drizzle 导出名）。
 * topic / action 一律走**参数**（`$1` / `$2`），不把字面量写死在 SQL 里，
 * 这样 `V9_TOPICS` 是唯一真源，改一处不会两边漂移。
 */
export const ACCEPTANCE_SQL = {
  /** $1 = topic（`V9_TOPICS.lpmRenderReady`） */
  countRenderReady: `SELECT COUNT(*)::int AS n FROM "events" WHERE topic = $1`,
  /** $1 = topic（`V9_TOPICS.lpmRenderReady`） */
  latestRenderReadyTrace: `SELECT trace_id FROM "events"
     WHERE topic = $1
     ORDER BY timestamp DESC LIMIT 1`,
  /** $1 = topic（`V9_TOPICS.personaRenderRequested`），$2 = trace_id */
  countRequestForTrace: `SELECT COUNT(*)::int AS n FROM "events"
     WHERE topic = $1 AND trace_id = $2`,
  /** $1 = action（`AUDIT_ACTION_RENDER_READY_WITHOUT_MATCHING_REQUEST`） */
  countOrphanAudit: `SELECT COUNT(*)::int AS n FROM "audit_log_entries" WHERE action = $1`,
} as const

interface AggregateLike { message?: string, errors: unknown[] }

/**
 * 判断是否 AggregateError（不直接 `instanceof`，避免依赖 lib 里是否有该全局类型）。
 *
 * 为什么需要：DSN 用 `localhost` 时 Node 会同时试 IPv6 与 IPv4，两个都失败时抛
 * `AggregateError`，而它的 `.message` 是**空字符串** —— 只打印 `.message` 会得到一行空白，
 * 恰恰是 `.env.local`（本仓默认 `localhost:5432`）最常见的情形。必须把 `.errors` 摊平。
 */
function isAggregateLike(err: unknown): err is AggregateLike {
  return typeof err === 'object'
    && err !== null
    && 'errors' in err
    && Array.isArray((err as { errors: unknown[] }).errors)
}

/** 把任意异常摊平成可读多行（含 AggregateError 的内层错误）。纯函数，可单测。 */
export function describeConnectionError(err: unknown): string[] {
  if (isAggregateLike(err)) {
    const inner = err.errors
      .map(e => (e instanceof Error ? (e.message || e.name) : String(e)))
      .filter(m => m.length > 0)
    const head = err.message && err.message.length > 0
      ? err.message
      : `AggregateError: ${inner.length} 个地址均连接失败`
    return inner.length > 0 ? [head, ...inner] : [head]
  }
  if (err instanceof Error)
    return [err.message || err.name]
  return [String(err)]
}

/**
 * 凭据脱敏。纯函数，可单测。
 *
 * 两种都要处理：(a) 整条 DSN 原样出现；(b) 任何 `scheme://user:pass@` 形态。
 * pg 的错误一般不回显 DSN，但配置写错时不能赌。
 */
export function redactSecrets(text: string, connectionString?: string): string {
  let out = text
  if (connectionString && connectionString.length > 0)
    out = out.split(connectionString).join('<DATABASE_URL redacted>')
  return out.replace(/:\/\/([^:/@\s]+):([^@/\s]+)@/g, '://$1:***@')
}

/** 机器可读结果（stdout 只输出它）。纯函数，可单测。字段名向后兼容既有消费方。 */
export function buildJsonReport(input: AcceptanceInput, verdict: AcceptanceVerdict) {
  return {
    topic: V9_TOPICS.lpmRenderReady,
    countLpmRenderReady: input.renderReadyCount,
    traceId: input.latestTraceId,
    topicPair: V9_TOPICS.personaRenderRequested,
    countPersonaRenderRequested: input.requestCountForLatestTrace,
    auditGapAction: AUDIT_ACTION_RENDER_READY_WITHOUT_MATCHING_REQUEST,
    auditGapCount: input.orphanAuditCount,
    result: verdict.pass ? 'PASS' : 'FAIL' as const,
    pass: verdict.pass,
    exitCode: verdict.exitCode,
  }
}

function reportTarget(connectionString: string): string {
  // 不打印连接串（含凭据）；只打印脱敏后的 host/db，便于确认打对了库。
  try {
    const u = new URL(connectionString)
    return `target: ${u.hostname}:${u.port || '5432'}${u.pathname}  (credentials omitted)`
  }
  catch {
    return 'target: <unparsable DATABASE_URL> (credentials omitted)'
  }
}

async function main(): Promise<void> {
  const jsonMode = process.argv.includes('--json')
  const connectionString = process.env.DATABASE_URL
  if (!connectionString) {
    console.error('FAIL: DATABASE_URL 未设置。请用 `pnpm run apply:env -- tsx scripts/accept-v9-render-loop.ts`，或在环境里显式提供。')
    process.exitCode = ACCEPT_EXIT.missingDatabaseUrl
    return
  }

  if (!jsonMode)
    console.info(`${reportTarget(connectionString)}\n`)

  const client = new Client({ connectionString })
  try {
    await client.connect()
  }
  catch (err) {
    console.error('FAIL: 无法连接运行库 —— 本脚本需要真实 Postgres 与真实数据。')
    for (const line of describeConnectionError(err))
      console.error(`  ${redactSecrets(line, connectionString)}`)
    process.exitCode = ACCEPT_EXIT.connectOrQueryError
    return
  }

  try {
    const ready = await client.query<{ n: number }>(
      ACCEPTANCE_SQL.countRenderReady,
      [V9_TOPICS.lpmRenderReady],
    )
    const renderReadyCount = ready.rows[0]?.n ?? 0

    let latestTraceId: string | null = null
    let requestCountForLatestTrace: number | null = null
    if (renderReadyCount > 0) {
      const latest = await client.query<{ trace_id: string }>(
        ACCEPTANCE_SQL.latestRenderReadyTrace,
        [V9_TOPICS.lpmRenderReady],
      )
      latestTraceId = latest.rows[0]?.trace_id ?? null
      if (latestTraceId !== null) {
        const paired = await client.query<{ n: number }>(
          ACCEPTANCE_SQL.countRequestForTrace,
          [V9_TOPICS.personaRenderRequested, latestTraceId],
        )
        requestCountForLatestTrace = paired.rows[0]?.n ?? 0
      }
    }

    const orphan = await client.query<{ n: number }>(
      ACCEPTANCE_SQL.countOrphanAudit,
      [AUDIT_ACTION_RENDER_READY_WITHOUT_MATCHING_REQUEST],
    )
    const orphanAuditCount = orphan.rows[0]?.n ?? 0

    const input: AcceptanceInput = {
      renderReadyCount,
      latestTraceId,
      requestCountForLatestTrace,
      orphanAuditCount,
    }
    const verdict = evaluateAcceptance(input)

    if (jsonMode) {
      console.info(JSON.stringify(buildJsonReport(input, verdict), null, 2))
    }
    else {
      for (const line of verdict.lines)
        console.info(line)
    }
    process.exitCode = verdict.exitCode
  }
  catch (err) {
    console.error('FAIL: 验收 SQL 执行失败（已连上库，但查询报错）。')
    for (const line of describeConnectionError(err))
      console.error(`  ${redactSecrets(line, connectionString)}`)
    process.exitCode = ACCEPT_EXIT.connectOrQueryError
  }
  finally {
    await client.end().catch(() => {})
  }
}

// 仅在被直接执行时跑 main（被 import 时（例如单测）不触发副作用）。
if (process.argv[1] && import.meta.url === `file://${process.argv[1]}`) {
  main().catch((err) => {
    console.error(err)
    process.exitCode = ACCEPT_EXIT.unexpected
  })
}
