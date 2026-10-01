#!/usr/bin/env node
/**
 * AIJADE 摄入时延基准装置（真实栈：真实 HTTP 服务器 + 真实 PostgreSQL + 真实 Redis）。
 *
 * ## 用途
 *
 * 复现论文中引用的摄入时延数字，即 `opinion_evaluation` 摄入接口在
 * 「顺序请求」与「并发请求」两种负载形态下的墙钟时延分布。
 *
 * 本装置存在的直接原因：论文 §5.7（英文稿 §5.7）曾引用
 * `8.1 / 10.6 / 29.6 / 291.3 / 325 ms` 等数字，但仓库中**没有任何一行代码可以复现它们**，
 * 该数字在投稿语境下因此不可发表。本装置把测量变成可执行的、可审计的行为。
 *
 * ## 用法
 *
 * ```bash
 * # 顺序摄入（默认 n=100）
 * node scripts/bench/ingest-latency.mjs --mode sequential --n 100
 *
 * # 并发摄入（默认并发度 = n，即一次性全部发出）
 * node scripts/bench/ingest-latency.mjs --mode concurrent --n 50
 *
 * # 两种模式连跑，并把原始样本落盘
 * node scripts/bench/ingest-latency.mjs --mode both --out bench-out/ingest-latency.json
 * ```
 *
 * 亦可经由 package.json 调用（见 `bench:ingest`）。
 *
 * ## 环境变量
 *
 * | 变量 | 默认值 | 说明 |
 * |---|---|---|
 * | `AIJADE_BENCH_BASE` | `http://localhost:3901/api/v1/v9/events` | 摄入端点 |
 * | `AIJADE_BENCH_TOKEN` | `e2e-test-token-aijade-2026` | Bearer 认证 token |
 *
 * ## 测量纪律（与论文 §5.7 的限定条件逐条对应）
 *
 * 本装置刻意把这些纪律做进默认行为，而不是留给调用者记住：
 *
 * 1. **预热丢弃**。默认丢弃前 `--warmup`（默认 10）个请求。首个请求承担连接池建立、
 *    TS/JS JIT、prepared statement 初始化、PG plan cache 冷启动——不丢弃会把冷启动
 *    成本摊进分位数。
 * 2. **原始样本全量落盘**。`--out` 写出每个请求的逐样本时延与状态码。
 *    **只报汇总分位数、不落原始样本的数字不可复核**，故本装置默认打印落盘路径。
 * 3. **分位数算法显式声明**。采用 nearest-rank（`ceil(p/100 × n)` 名次），
 *    不做插值。**n 较小时 p99 在统计上等于最大值**，落盘文件里同时给出
 *    `n`、`min`、`max`，读取者应据此判断哪些分位数不可信。
 * 4. **失败即失败**。任何非 201 计入 `errors`；`errors > 0` 时进程以非零码退出。
 *    不允许"报零失败"与"实际有错"并存。
 * 5. **幂等键逐请求唯一**。`idempotency_key` 承担去重，若复用同一个键，
 *    后续请求会被去重而测不到写入成本——这会让数字系统性偏乐观。
 * 6. **认证成本如实声明**。走 Bearer token 直连通道，**不含真实会话解析成本**。
 *    引用本装置产出的数字时必须一并声明此点。
 *
 * ## 本装置不做什么
 *
 * - 不归因。并发相对顺序的退化（论文记为约 36×）来自连接池饱和 / 事务串行化 /
 *   投影行争用中的哪一项，本装置只测现象，不做归因。
 * - 不预置数据。空库与有数据时的写入成本不同；若要测有数据的情形，
 *   先自行灌入数据并记录行数（论文 §5.7 限定条件 4）。
 * - 不构成容量上限或 SLA。零失败只能按三法则推出该量级失败率的上界，
 *   不能反推容量。
 */

import { createHash } from 'node:crypto'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'

// ---------------------------------------------------------------------------
// 配置
// ---------------------------------------------------------------------------

const BASE = process.env.AIJADE_BENCH_BASE ?? 'http://localhost:3901/api/v1/v9/events'
const TOKEN = process.env.AIJADE_BENCH_TOKEN ?? 'e2e-test-token-aijade-2026'
const TOPIC = 'aijade.learning.constraint.opinion_evaluation'

const argv = process.argv.slice(2)
function arg(name, fallback) {
  const i = argv.indexOf(`--${name}`)
  return i >= 0 && argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[i + 1] : fallback
}
const MODE = arg('mode', 'both') // sequential | concurrent | both
const N = Number(arg('n', '100'))
const WARMUP = Number(arg('warmup', '10'))
const OUT = arg('out', null)
const TIMEOUT_MS = Number(arg('timeout', '30000'))

if (!['sequential', 'concurrent', 'both'].includes(MODE)) {
  console.error(`未知 --mode：${MODE}（可选 sequential | concurrent | both）`)
  process.exit(2)
}
if (!Number.isInteger(N) || N <= 0) {
  console.error(`--n 必须为正整数，收到：${arg('n', '100')}`)
  process.exit(2)
}

// ---------------------------------------------------------------------------
// 请求构造
// ---------------------------------------------------------------------------

let seq = 0
/** `tick` 起点：抬高以免与既有小 tick 相撞；上限受 int32 约束。 */
const TICK_BASE = 1_000_000
/** int32 上限，与服务端 `tickInt` / 内核 `.max()` 一致。 */
const INT32_MAX = 2_147_483_647

/**
 * 构造一条 `opinion_evaluation` 事件信封。
 *
 * 契约来源：`apps/server/src/routes/v9/schema.ts`
 *  - `v9EventEnvelopeSchema` 的信封必填字段
 *  - `v10EventFieldsSchema`：learning/video 类事件**强制**要求 `tick` 与
 *    `causality.inputHash`（服务端会以 `INVALID_V10_EVENT` 拒绝缺这两项的请求）
 *  - `V9_PAYLOAD_SCHEMAS['aijade.learning.constraint.opinion_evaluation']`
 */
function envelope(tick) {
  const id = `bench-${Date.now().toString(36)}-${(seq++).toString(36)}-${Math.random().toString(36).slice(2, 8)}`
  const payload = {
    evaluation_target: 'bench-target',
    claims: [{ claim_text: 'bench claim', confidence: 0.5 }],
    uncertainty_notes: 'bench run; not a scientific claim',
  }
  // inputHash 是输入快照的内容身份；用规范化 JSON 的 sha256 hex，逐请求唯一。
  const inputHash = createHash('sha256').update(JSON.stringify(payload)).update(id).digest('hex')
  return {
    event_id: id,
    trace_id: `trace-${id}`,
    correlation_id: `corr-${id}`,
    timestamp: Date.now(),
    producer: 'bench-ingest-latency',
    origin_device: 'bench-host',
    privacy_level: 1,
    evidence_refs: [],
    causal_context_refs: [],
    risk_score: 0.1,
    // 逐请求唯一 —— 复用会使后续请求被去重，测不到写入成本（纪律 5）
    idempotency_key: `idem-${id}`,
    replay_mode: 'live',
    risk_level: 'low',
    tick: tick % INT32_MAX,
    causality: { inputHash },
    topic: TOPIC,
    payload,
  }
}

/** 发一条请求，返回墙钟时延（ms）与状态码。时延只计到响应头读毕。 */
async function timedRequest(tick) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
  const t0 = performance.now()
  try {
    const res = await fetch(BASE, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'authorization': `Bearer ${TOKEN}` },
      body: JSON.stringify(envelope(tick)),
      signal: controller.signal,
    })
    // 必须把 body 读完，否则连接不归还，后续请求的分位数会被污染
    await res.arrayBuffer()
    return { ms: performance.now() - t0, status: res.status }
  }
  catch (err) {
    return { ms: performance.now() - t0, status: 0, error: err?.name ?? String(err) }
  }
  finally {
    clearTimeout(timer)
  }
}

// ---------------------------------------------------------------------------
// 统计
// ---------------------------------------------------------------------------

/**
 * nearest-rank 分位数（不做插值）。
 * 名次 = ceil(p/100 × n)，1-based；n 很小时 p99 会等于 max，这是算法的性质而非缺陷。
 */
function percentile(sorted, p) {
  if (sorted.length === 0)
    return null
  const rank = Math.ceil((p / 100) * sorted.length)
  return sorted[Math.min(Math.max(rank, 1), sorted.length) - 1]
}

function summarize(samples) {
  const ok = samples.filter(s => s.status === 201)
  const errors = samples.filter(s => s.status !== 201)
  const ms = ok.map(s => s.ms).sort((a, b) => a - b)
  const sum = ms.reduce((a, b) => a + b, 0)
  return {
    n: ms.length,
    errors: errors.length,
    errorDetail: errors.length
      ? Object.entries(
          errors.reduce((acc, e) => {
            const k = e.status === 0 ? `network:${e.error ?? 'unknown'}` : `http:${e.status}`
            acc[k] = (acc[k] ?? 0) + 1
            return acc
          }, {}),
        ).map(([k, v]) => `${k}×${v}`)
      : [],
    min: ms.length ? ms[0] : null,
    max: ms.length ? ms[ms.length - 1] : null,
    mean: ms.length ? sum / ms.length : null,
    p50: percentile(ms, 50),
    p95: percentile(ms, 95),
    p99: percentile(ms, 99),
    /** p99 是否退化为 max —— 供读取者判断该分位数是否可信 */
    p99EqualsMax: ms.length > 0 && percentile(ms, 99) === ms[ms.length - 1],
    raw: ms,
  }
}

function fmt(v) {
  return v === null ? '  —  ' : `${v.toFixed(1)} ms`
}

function report(label, s) {
  console.log('')
  console.log(`── ${label} ─────────────────────────────────────────`)
  console.log(`  样本 n=${s.n}   失败 ${s.errors}${s.errorDetail.length ? `（${s.errorDetail.join(', ')}）` : ''}`)
  console.log(`  min ${fmt(s.min)}   p50 ${fmt(s.p50)}   p95 ${fmt(s.p95)}   p99 ${fmt(s.p99)}   max ${fmt(s.max)}   mean ${fmt(s.mean)}`)
  if (s.p99EqualsMax)
    console.log('  ⚠️  p99 == max：样本量不足以支撑第 99 百分位，引用时请勿单独引用 p99')
}

// ---------------------------------------------------------------------------
// 模式
// ---------------------------------------------------------------------------

/** tick 分配器：全局单调递增，保证每条事件在排序语义上唯一。 */
let tickCounter = TICK_BASE
function nextTick() {
  return tickCounter++
}

/** 顺序摄入：一次一发，等上一发结束再发下一发。 */
async function runSequential(n, warmup) {
  const warm = []
  for (let i = 0; i < warmup; i++)
    warm.push(await timedRequest(nextTick()))

  const samples = []
  for (let i = 0; i < n; i++)
    samples.push(await timedRequest(nextTick()))

  return { samples, warmupSamples: warm }
}

/** 并发摄入：并发度 = n，一次性全部发出。 */
async function runConcurrent(n, warmup) {
  const warm = []
  for (let i = 0; i < warmup; i++)
    warm.push(await timedRequest(nextTick()))

  const ticks = Array.from({ length: n }, () => nextTick())
  const t0 = performance.now()
  const samples = await Promise.all(ticks.map(t => timedRequest(t)))
  const wallClockMs = performance.now() - t0

  return { samples, warmupSamples: warm, wallClockMs }
}

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------

async function main() {
  console.log(`摄入时延基准 · ${BASE}`)
  console.log(`mode=${MODE}  n=${N}  warmup=${WARMUP}  (分位数算法：nearest-rank，不插值)`)

  // 连通性预检：把"服务器没起来"与"基准跑出坏数字"区分开
  const probe = await timedRequest(nextTick())
  if (probe.status === 0) {
    console.error(`\n预检失败：${BASE} 不可达（${probe.error ?? 'network error'}）。`)
    console.error('请先启动服务端（含 PG + Redis + worker），再运行本装置。')
    process.exit(3)
  }
  if (probe.status !== 201) {
    console.error(`\n预检失败：端点返回 ${probe.status}，非 201。请核对 AIJADE_BENCH_TOKEN 与库状态。`)
    process.exit(3)
  }
  console.log('预检通过（201）。\n')

  const out = {
    base: BASE,
    mode: MODE,
    n: N,
    warmup: WARMUP,
    startedAt: new Date().toISOString(),
    // 测量限定条件的自证字段：引用数字时必须随数字一并给出
    provenance: {
      percentileMethod: 'nearest-rank (no interpolation)',
      authPath: 'Bearer static token (TEST_AUTH_TOKEN); real session resolution NOT exercised',
      warmupDiscarded: WARMUP,
      // 由操作者填写：测前库内行数，如 'events=8,render_traces=1'
      dbRowCounts: process.env.AIJADE_BENCH_DB_ROWS ?? '(not recorded)',
      tickBase: TICK_BASE,
      node: process.version,
      platform: `${process.platform}/${process.arch}`,
    },
    runs: {},
  }
  let totalErrors = 0

  if (MODE === 'sequential' || MODE === 'both') {
    const { samples, warmupSamples } = await runSequential(N, WARMUP)
    const s = summarize(samples)
    report(`顺序摄入（sequential, n=${N}, 丢弃前 ${WARMUP}）`, s)
    totalErrors += s.errors
    out.runs.sequential = {
      requested: N,
      warmupDiscarded: warmupSamples.length,
      wallClockMs: null,
      ...s,
      // 逐样本明细（纪律 2）
      detailed: samples.map(x => ({ ms: Number(x.ms.toFixed(3)), status: x.status })),
    }
  }

  if (MODE === 'concurrent' || MODE === 'both') {
    const { samples, warmupSamples, wallClockMs } = await runConcurrent(N, WARMUP)
    const s = summarize(samples)
    report(`并发摄入（concurrent, 并发度 ${N}, 丢弃前 ${WARMUP}）`, s)
    console.log(`  墙钟（全部发出到全部返回） ${wallClockMs.toFixed(1)} ms`)
    totalErrors += s.errors
    out.runs.concurrent = {
      requested: N,
      concurrency: N,
      warmupDiscarded: warmupSamples.length,
      wallClockMs: Number(wallClockMs.toFixed(3)),
      ...s,
      detailed: samples.map(x => ({ ms: Number(x.ms.toFixed(3)), status: x.status })),
    }
  }

  if (OUT) {
    const path = resolve(process.cwd(), OUT)
    mkdirSync(dirname(path), { recursive: true })
    out.finishedAt = new Date().toISOString()
    writeFileSync(path, `${JSON.stringify(out, null, 2)}\n`, 'utf8')
    console.log(`\n原始样本已落盘：${path}`)
    console.log('引用数字时请一并声明：认证走 Bearer 直连（不含会话解析成本）、样本量与库内数据量见落盘文件。')
  }
  else {
    console.log('\n未指定 --out，原始样本未落盘。')
    console.log('⚠️  仅凭控制台分位数不足以复核结论，建议加 --out <path> 保留逐样本明细。')
  }

  if (totalErrors > 0) {
    console.error(`\n退出码 1：共 ${totalErrors} 条请求非 201。`)
    process.exit(1)
  }
  console.log('\n完成：全部请求返回 201。')
}

main().catch((err) => {
  console.error('基准装置异常终止：', err)
  process.exit(1)
})
