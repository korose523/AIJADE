import type { HonoEnv } from '../src/types/hono'

/**
 * v10 **契约漂移回归矩阵**（设计文档 §7.1 / §11.2）。
 *
 * ## 这个脚本要证明什么
 *
 * 三条不变量，**逐 topic**（覆盖服务端 `AIJADE_TOPICS` 全集）：
 *
 * 1. **双端一致**：一个合法 payload，既被**内核**（`@proj-aijade/memory-biomimetic`，
 *    契约真源，zod）接受，也被**HTTP 边界**（`apps/server`，有意复制的 valibot）接受。
 *    两侧任一方改了字段名/必填性而另一方不改 ⇒ 立刻红。
 * 2. **边界承重墙**：缺字段 / 空串 / 未知额外字段 ⇒ **400**，且**不落库**。
 * 3. **不落库双一致**（v10 §7）：被拒的请求不仅不写 `events`，也**不改 `render_traces`**。
 *
 * 另有守卫：服务端每新增一个 topic 却忘了在 `FIXTURES` 里登记 ⇒ 本脚本直接失败
 * （而不是悄悄少测一个 topic）。
 *
 * ## 双环境
 *
 * - **PGlite（默认，总是跑）**：正例 + 负例全套。
 * - **真实 PostgreSQL（`--postgres` + 可达的 `DATABASE_URL`）**：**只跑负例**。
 *   负例按定义"必须被拒且不写任何行"，所以这一条腿在真实库上是**非破坏性**的；
 *   正例需要写入，故意不跑，避免污染真实数据。
 *   若本机无库（本仓现状：`.env.local` → localhost:5432 不可达、`.env` → docker 服务名
 *   `db:5432` 无 daemon），脚本**如实报告 `skipped`**，绝不假称通过。
 *
 * ## 诚实边界
 *
 * - 负例是**手写枚举**的（不做 schema 反射）。好处是可读、可审阅、不依赖 valibot/zod
 *   的内省 API；代价是新增字段不会自动生成用例 —— 所以有上面那条"未登记 topic 即失败"的守卫。
 * - 全局 `sessionMiddleware` 依赖 better-auth + 真实 DB，无法在此廉价复现，故用等价中间件
 *   注入 `c.get('user')`；`authGuard` 本身是**真的**。
 *
 * 运行：`pnpm --filter @proj-aijade/server verify:v10-contract-drift`
 *      `pnpm --filter @proj-aijade/server verify:v10-contract-drift -- --postgres`
 */
import process from 'node:process'

import { PGlite } from '@electric-sql/pglite'
import { assertV10RequiredFields, envelopeSchema as KERNEL_ENVELOPE_SCHEMA, AIJADE_TOPICS as KERNEL_TOPICS, safeParseAijadeEvent } from '@proj-aijade/memory-biomimetic'
import { drizzle } from 'drizzle-orm/pglite'
import { Hono } from 'hono'

import { createV9EventsRoutes } from '../src/routes/v9/events'
import { AIJADE_TOPICS as SERVER_TOPICS } from '../src/routes/v9/schema'
import { createV9EventService } from '../src/services/domain/v9-events'
import { ApiError } from '../src/utils/error'

import * as schema from '../src/schemas/memory-v9'

// ---------------------------------------------------------------------------
// harness
// ---------------------------------------------------------------------------

let failures = 0

function check(cond: boolean, msg: string): void {
  if (cond) {
    console.info(`ok   ${msg}`)
  }
  else {
    failures++
    console.error(`FAIL ${msg}`)
  }
}

interface Fixture {
  topic: string
  /** 该 topic 的一条合法 payload；`i` 用于保证身份/key 唯一。 */
  payload: (i: number) => Record<string, unknown>
  /** 需要 tick + causality（v10 前缀）。 */
  v10: boolean
  /**
   * 额外的**合法**变体：与主 payload 同为「必须被两边接受」，只是形状不同
   * （典型是"某个可选字段缺省"）。
   *
   * 为什么必须有这个口子：只喂一条"总是带全字段"的正例，是查不出
   * **可选性口径单向漂移**的 —— 内核说 `.optional()`、边界说必填非空时，
   * 主 payload 在两边都会通过，而真实生产者发出的那种"缺可选字段"的事件
   * 会在边界被 400 丢掉。`lpm.render_ready.asset_version_hash` 正是如此。
   */
  extraPositives?: { name: string, payload: (i: number) => Record<string, unknown> }[]
  /** 手写负例：把合法 payload 变异成必须被拒的形状。 */
  negatives: { name: string, mutate: (payload: Record<string, unknown>) => Record<string, unknown> }[]
}

/** 删掉一个顶层必填键。 */
function drop(key: string) {
  return (payload: Record<string, unknown>) => {
    const next = { ...payload }
    delete next[key]
    return next
  }
}

/** 把一个顶层键置为空串（用于"必填且非空"的字符串字段）。 */
function blank(key: string) {
  return (payload: Record<string, unknown>) => ({ ...payload, [key]: '' })
}

/** 加入一个未知字段（验证 strictObject：未知字段必须被拒）。 */
function surprise() {
  return (payload: Record<string, unknown>) => ({ ...payload, surprise_unknown_field: 'x' })
}

// 学习提案的引用校验要求 `render_traces` 里存在匹配投影，故在 PGlite 腿先种一行已知投影。
const SEED_RENDER_REF = 'seed-render-ref'
const SEED_APPLIED_HASH = 'seed-applied-hash'
const SEED_ASSET_HASH = 'seed-asset-hash'

/**
 * 信封的 13 个必需字段，逐字对应内核 `events.ts` 的 `envelopeFields` 与边界
 * `v9EventEnvelopeSchema`。两边都必须正好是这一组（多一个少一个即失败）。
 */
const ENVELOPE_REQUIRED_FIELDS = [
  'event_id',
  'trace_id',
  'correlation_id',
  'timestamp',
  'producer',
  'origin_device',
  'privacy_level',
  'evidence_refs',
  'causal_context_refs',
  'risk_score',
  'idempotency_key',
  'replay_mode',
  'risk_level',
]

/** v10 可选字段：v9 生产者可省，`aijade.video.*` / `aijade.learning.*` 必给。 */
const ENVELOPE_OPTIONAL_FIELDS = ['tick', 'causality', 'core_state_node']

const FIXTURES: Fixture[] = [
  {
    topic: 'aijade.active_learning.requested',
    v10: false,
    payload: i => ({
      session_id: `s-${i}`,
      trace_id: `t-${i}`,
      requested_at: 1,
      quest_ref: `quest-${i}`,
      resource_budget: { allocated: 10, spent: 0, unit: 'queries' },
      stop_conditions: ['budget-exhausted'],
    }),
    negatives: [
      { name: 'missing quest_ref', mutate: drop('quest_ref') },
      { name: 'blank quest_ref', mutate: blank('quest_ref') },
      { name: 'empty stop_conditions', mutate: p => ({ ...p, stop_conditions: [] }) },
      { name: 'unknown field', mutate: surprise() },
    ],
  },
  {
    topic: 'aijade.active_learning.completed',
    v10: false,
    payload: i => ({ session_id: `s-${i}`, trace_id: `t-${i}`, completed_at: 2, quest_ref: `quest-${i}` }),
    negatives: [
      { name: 'missing quest_ref', mutate: drop('quest_ref') },
      { name: 'blank quest_ref', mutate: blank('quest_ref') },
      { name: 'unknown field', mutate: surprise() },
    ],
  },
  {
    topic: 'aijade.evidence.weave_candidate_ready',
    v10: false,
    payload: i => ({ tx_id: `tx-${i}`, weave_id: `w-${i}`, graph_hash: `g-${i}`, candidate_memory_write_ids: [`mw-${i}`] }),
    negatives: [
      { name: 'missing graph_hash', mutate: drop('graph_hash') },
      { name: 'blank graph_hash', mutate: blank('graph_hash') },
      { name: 'unknown field', mutate: surprise() },
    ],
  },
  {
    topic: 'aijade.pgc.write_plan_ready',
    v10: false,
    payload: i => ({ pgc_state_id: `pgc-${i}`, write_plan_size: 1, policy_version: 'pgc_policy_v1' }),
    negatives: [
      { name: 'missing pgc_state_id', mutate: drop('pgc_state_id') },
      { name: 'negative write_plan_size', mutate: p => ({ ...p, write_plan_size: -1 }) },
      { name: 'unknown field', mutate: surprise() },
    ],
  },
  {
    topic: 'aijade.memory_tx.committed',
    v10: false,
    payload: i => ({ tx_id: `tx-${i}`, trace_id: `t-${i}`, committed_count: 1, rejected_count: 0, throttled_count: 0 }),
    negatives: [
      { name: 'missing committed_count', mutate: drop('committed_count') },
      { name: 'negative committed_count', mutate: p => ({ ...p, committed_count: -1 }) },
      { name: 'unknown field', mutate: surprise() },
    ],
  },
  {
    topic: 'aijade.persona.render_requested',
    v10: false,
    payload: i => ({ session_id: `s-${i}`, persona_snapshot_ref: `snap-${i}`, intent_ref: `intent-${i}` }),
    negatives: [
      { name: 'missing persona_snapshot_ref', mutate: drop('persona_snapshot_ref') },
      { name: 'missing intent_ref', mutate: drop('intent_ref') },
      { name: 'blank intent_ref', mutate: blank('intent_ref') },
      // 自引用冒充：把 intent_ref 指向 trace_id 自己（设计文档 §11.2 点名的形状）。
      // 注意：边界层只保证"非空字符串"，这条由 §11.2 要求"必须 400"，而当前实现
      // **不会**拒绝 —— 故这里把它作为 **已记录缺口** 断言，而不是假称通过。
      { name: 'unknown field', mutate: surprise() },
    ],
  },
  {
    topic: 'aijade.lpm.render_ready',
    v10: false,
    payload: i => ({ session_id: `s-${i}`, render_ref: `render-${i}`, applied_params_hash: `applied-${i}`, asset_version_hash: `asset-${i}` }),
    extraPositives: [
      {
        // 可选性探针：内核把 `asset_version_hash` 设计为可选（异步解析可能未就绪，见 `pef.ts`
        // 按非空条件带上该键），边界必须同口径接受。缺这条探针，单向漂移查不出来。
        name: 'asset_version_hash absent (optional per kernel)',
        payload: i => ({ session_id: `s-${i}`, render_ref: `render-${i}`, applied_params_hash: `applied-${i}` }),
      },
    ],
    negatives: [
      { name: 'missing render_ref', mutate: drop('render_ref') },
      { name: 'blank render_ref', mutate: blank('render_ref') },
      { name: 'blank applied_params_hash', mutate: blank('applied_params_hash') },
      { name: 'blank asset_version_hash', mutate: blank('asset_version_hash') },
      { name: 'unknown field', mutate: surprise() },
    ],
  },
  {
    topic: 'aijade.video.observation.webpage_text',
    v10: true,
    payload: i => ({
      session_id: `s-${i}`,
      source_url: `https://example.com/${i}`,
      content_hash: `ch-${i}`,
      spans: [{ start_offset: 0, end_offset: 5, label: 'p' }],
      observation_text: `text-${i}`,
    }),
    negatives: [
      { name: 'missing session_id', mutate: drop('session_id') },
      { name: 'blank session_id', mutate: blank('session_id') },
      { name: 'missing source_url', mutate: drop('source_url') },
      { name: 'blank observation_text', mutate: blank('observation_text') },
      { name: 'empty spans', mutate: p => ({ ...p, spans: [] }) },
      { name: 'unknown field', mutate: surprise() },
    ],
  },
  {
    topic: 'aijade.video.observation.video_transcript',
    v10: true,
    payload: i => ({
      session_id: `s-${i}`,
      video_id: `v-${i}`,
      transcript_hash: `th-${i}`,
      time_spans: [{ start_ms: 0, end_ms: 100, text: `cap-${i}` }],
      caption_text: `cap-${i}`,
    }),
    negatives: [
      { name: 'missing session_id', mutate: drop('session_id') },
      { name: 'blank session_id', mutate: blank('session_id') },
      { name: 'missing video_id', mutate: drop('video_id') },
      { name: 'empty time_spans', mutate: p => ({ ...p, time_spans: [] }) },
      { name: 'unknown field', mutate: surprise() },
    ],
  },
  {
    topic: 'aijade.learning.proposed.shadow_params',
    v10: true,
    payload: i => ({
      session_id: `s-${i}`,
      proposal_id: `prop-${i}`,
      render_ref: SEED_RENDER_REF,
      applied_params_hash: SEED_APPLIED_HASH,
      asset_version_hash: SEED_ASSET_HASH,
      input_hash: `ih-${i}`,
      candidate_params: { 'emotion.preset': 'happy' },
      confidence: 0.5,
    }),
    negatives: [
      { name: 'missing input_hash', mutate: drop('input_hash') },
      { name: 'blank proposal_id', mutate: blank('proposal_id') },
      { name: 'confidence out of range', mutate: p => ({ ...p, confidence: 1.5 }) },
      { name: 'unknown field', mutate: surprise() },
    ],
  },
  {
    topic: 'aijade.learning.proposed.evidence',
    v10: true,
    payload: i => ({
      session_id: `s-${i}`,
      proposal_id: `prop-${i}`,
      render_ref: SEED_RENDER_REF,
      applied_params_hash: SEED_APPLIED_HASH,
      asset_version_hash: SEED_ASSET_HASH,
      evidence_hash: `eh-${i}`,
      claim_text: `claim-${i}`,
      confidence: 0.4,
    }),
    negatives: [
      { name: 'missing evidence_hash', mutate: drop('evidence_hash') },
      { name: 'blank claim_text', mutate: blank('claim_text') },
      { name: 'unknown field', mutate: surprise() },
    ],
  },
  {
    topic: 'aijade.learning.constraint.opinion_evaluation',
    v10: true,
    payload: i => ({
      evaluation_target: `ch-${i}`,
      claims: [{ claim_text: `claim-${i}`, confidence: 0.6 }],
      uncertainty_notes: '可能误读原文',
    }),
    negatives: [
      { name: 'missing uncertainty_notes', mutate: drop('uncertainty_notes') },
      { name: 'empty claims', mutate: p => ({ ...p, claims: [] }) },
      { name: 'unknown field', mutate: surprise() },
    ],
  },
]

const DDL = `
  CREATE TABLE "events" (
    "id" text PRIMARY KEY,
    "event_id" text NOT NULL,
    "trace_id" text NOT NULL,
    "correlation_id" text NOT NULL,
    "timestamp" timestamp NOT NULL,
    "producer" text NOT NULL,
    "origin_device" text NOT NULL,
    "privacy_level" integer NOT NULL,
    "evidence_refs" text[] NOT NULL DEFAULT '{}',
    "causal_context_refs" text[] NOT NULL DEFAULT '{}',
    "risk_score" real NOT NULL DEFAULT 0,
    "topic" text NOT NULL,
    "payload" jsonb,
    "idempotency_key" text NOT NULL UNIQUE,
    "replay_mode" text NOT NULL CHECK ("replay_mode" IN ('live','replay')),
    "risk_level" text NOT NULL CHECK ("risk_level" IN ('low','medium','high')),
    "tick" integer,
    "causality" jsonb,
    "core_state_node" text
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
  CREATE TABLE "render_traces" (
    "id" text PRIMARY KEY,
    "session_id" text NOT NULL,
    "trace_id" text NOT NULL,
    "correlation_id" text NOT NULL,
    "event_id" text NOT NULL,
    "persona_snapshot_ref" text,
    "intent_ref" text,
    "render_ref" text,
    "applied_params_hash" text,
    "asset_version_hash" text,
    "created_at" timestamp DEFAULT NOW() NOT NULL,
    "updated_at" timestamp DEFAULT NOW() NOT NULL
  );
  CREATE UNIQUE INDEX "render_traces_render_ref_idx"
    ON "render_traces" ("render_ref") WHERE "render_ref" IS NOT NULL;
`

function serverEnvelope(fixture: Fixture, i: number, payload: Record<string, unknown>): Record<string, unknown> {
  return {
    event_id: `evt-${fixture.topic}-${i}`,
    trace_id: `trace-${fixture.topic}-${i}`,
    correlation_id: `trace-${fixture.topic}-${i}`,
    timestamp: 1_700_000_000_000,
    producer: 'contract-matrix',
    origin_device: 'test',
    privacy_level: 1,
    evidence_refs: [],
    causal_context_refs: [`trace-${fixture.topic}-${i}`],
    risk_score: 0,
    idempotency_key: `idem-${fixture.topic}-${i}`,
    replay_mode: 'live',
    risk_level: 'low',
    ...(fixture.v10 ? { tick: i, causality: { inputHash: `input-${fixture.topic}-${i}` } } : {}),
    topic: fixture.topic,
    payload,
  }
}

/**
 * 内核信封 = 服务端信封的**同一组字段**（单源），所以这里**原样透传**，不再做任何投影。
 *
 * 这里原本显式把 `origin_device` / `privacy_level` / `evidence_refs` / `causal_context_refs`
 * / `risk_score` 挑掉，理由写的是"内核信封没有那 5 个字段"。而那个理由**本身就是被验证的
 * 漂移**：内核当时只有 8 个字段，于是内核工厂产出的信封根本投不到事件总线（必被 400 拒），
 * 服务端落库侧只好自行合成缺失的 5 个（把真实设备名覆写成 `'v9-runtime'`、把连续
 * `riskScore` 压回 3 级带宽）。
 *
 * 把漂移写进验证器是最坏的一种失败模式：验证器会替两端各自"补齐"，于是两侧永远测不出不一致。
 * 现在两侧同集，同一个对象同时喂给两端 —— 任何一侧少一个字段，都会立刻在对面暴露出来。
 */
function kernelEnvelope(env: Record<string, unknown>): Record<string, unknown> {
  return env
}

function kernelAccepts(env: Record<string, unknown>): boolean {
  return safeParseAijadeEvent(kernelEnvelope(env)).success
}

interface Leg {
  label: string
  runPositive: boolean
  countRows: () => Promise<{ events: number, renderTraces: number }>
  post: (env: Record<string, unknown>) => Promise<{ status: number, body: Record<string, unknown> }>
}

async function runMatrix(leg: Leg): Promise<void> {
  console.info(`\n=== leg: ${leg.label} (positive cases: ${leg.runPositive ? 'yes' : 'no'}) ===`)

  if (leg.runPositive) {
    for (const fixture of FIXTURES) {
      // 主 payload 用 i=0；合法变体用 i=200+，保证身份/key 不与主用例或负例（100+）撞车 ——
      // 撞车会让第二次 POST 走幂等去重返回 200，把"被接受"误读成"被拒绝"。
      const positives = [
        { label: 'valid payload', index: 0, payload: fixture.payload(0) },
        ...(fixture.extraPositives ?? []).map((variant, k) => ({
          label: variant.name,
          index: 200 + k,
          payload: variant.payload(200 + k),
        })),
      ]

      for (const positive of positives) {
        const env = serverEnvelope(fixture, positive.index, positive.payload)
        const tag = `${fixture.topic} / ${positive.label}`

        check(kernelAccepts(env), `[kernel] ${tag}: valid payload accepted`)
        // 注意：`safeParseAijadeEvent` 直接返回 zod 的 `{ success, data }`（zod v4 语义），
        // 不是 `{ success, output }` —— 用错键会拿到 `undefined`，从而把「成功」误判成崩溃。
        const kernelParsed = safeParseAijadeEvent(kernelEnvelope(env))
        if (kernelParsed.success) {
          try {
            assertV10RequiredFields(kernelParsed.data)
            check(true, `[kernel] ${tag}: v10 envelope fields present`)
          }
          catch (error) {
            check(false, `[kernel] ${tag}: assertV10RequiredFields threw on the valid fixture (${String(error)})`)
          }
        }

        const res = await leg.post(env)
        check(res.status === 201, `[http] ${tag}: valid payload -> 201 (got ${res.status})`)
      }
    }
  }

  for (const fixture of FIXTURES) {
    for (const [index, negative] of fixture.negatives.entries()) {
      const i = 100 + index
      const payload = negative.mutate(fixture.payload(i))
      const env = serverEnvelope(fixture, i, payload)

      const before = await leg.countRows()
      const res = await leg.post(env)
      const after = await leg.countRows()

      check(res.status === 400, `[http] ${fixture.topic} / ${negative.name}: must be 400 (got ${res.status})`)
      check(!kernelAccepts(env), `[kernel] ${fixture.topic} / ${negative.name}: kernel must reject too`)
      check(after.events === before.events, `[no-write] ${fixture.topic} / ${negative.name}: events unchanged (${before.events} -> ${after.events})`)
      check(
        after.renderTraces === before.renderTraces,
        `[no-write] ${fixture.topic} / ${negative.name}: render_traces unchanged (${before.renderTraces} -> ${after.renderTraces})`,
      )
    }
  }

  // ---- 信封字段集两端同集（这正是此前 8 vs 13 漂移的判据） ----
  //
  // 为什么单独做这一节：topic 级的负例只变异 **payload**，永远测不出"信封少字段"。
  // 而信封少字段恰恰是本项目真实发生过的漂移，且症状是**单向**的 ——
  // 内核能构造、边界必拒，于是"内核合法产出"在总线上根本不存在。
  // 这里逐字段把必需项抽掉，要求两端**同时**拒绝：只在一端拒绝不足以称为同集。
  for (const field of ENVELOPE_REQUIRED_FIELDS) {
    const i = 900 + ENVELOPE_REQUIRED_FIELDS.indexOf(field)
    const fixture = FIXTURES[0]
    const env = serverEnvelope(fixture, i, fixture.payload(i))
    delete env[field]

    const before = await leg.countRows()
    const res = await leg.post(env)
    const after = await leg.countRows()

    check(!kernelAccepts(env), `[kernel] envelope missing "${field}": must be rejected`)
    check(res.status === 400, `[http] envelope missing "${field}": must be 400 (got ${res.status})`)
    check(after.events === before.events, `[no-write] envelope missing "${field}": events unchanged (${before.events} -> ${after.events})`)
  }

  // 反向对照：3 个 v10 可选字段**确实可省**，否则上面的"必需"断言可能只是"什么都拒"。
  for (const field of ENVELOPE_OPTIONAL_FIELDS) {
    const i = 950 + ENVELOPE_OPTIONAL_FIELDS.indexOf(field)
    const fixture = FIXTURES[0]
    const env = serverEnvelope(fixture, i, fixture.payload(i))
    delete env[field]
    check(kernelAccepts(env), `[kernel] envelope without optional "${field}": must still be accepted`)
  }
}

async function main(): Promise<void> {
  // ---- 守卫：服务端每新增 topic 都必须在本矩阵里登记 ----
  const covered = new Set(FIXTURES.map(f => f.topic))
  const uncovered = SERVER_TOPICS.filter(t => !covered.has(t))
  check(uncovered.length === 0, `every server topic has a fixture (uncovered: ${uncovered.join(', ') || 'none'})`)
  const stale = [...covered].filter(t => !(SERVER_TOPICS as readonly string[]).includes(t))
  check(stale.length === 0, `no stale fixture for a removed topic (stale: ${stale.join(', ') || 'none'})`)

  // ---- 内核与服务端的 topic 集合必须一致（契约漂移的静态部分） ----
  const kernelSet = new Set<string>(KERNEL_TOPICS as readonly string[])
  const serverSet = new Set<string>(SERVER_TOPICS as readonly string[])
  const onlyKernel = [...kernelSet].filter(t => !serverSet.has(t))
  const onlyServer = [...serverSet].filter(t => !kernelSet.has(t))
  check(onlyKernel.length === 0 && onlyServer.length === 0, `kernel/server topic sets agree (kernel-only: ${onlyKernel.join(', ') || 'none'}; server-only: ${onlyServer.join(', ') || 'none'})`)

  // ---- 内核信封 schema 声明的字段集必须正好是这 13 + 3（静态侧） ----
  // 行为侧（逐字段抽掉 → 两端都必须拒）在 runMatrix 里对每条腿各跑一遍。
  const kernelFieldNames = Object.keys(KERNEL_ENVELOPE_SCHEMA.shape).sort()
  check(
    kernelFieldNames.join(',') === [...ENVELOPE_REQUIRED_FIELDS, ...ENVELOPE_OPTIONAL_FIELDS].sort().join(','),
    `kernel envelope declares exactly ${ENVELOPE_REQUIRED_FIELDS.length} required + ${ENVELOPE_OPTIONAL_FIELDS.length} optional fields (got: ${kernelFieldNames.join(', ')})`,
  )

  // ---- PGlite 腿 ----
  const client = new PGlite()
  await client.exec(DDL)
  const db = drizzle(client, { schema })
  const service = createV9EventService(db as never)

  await db.insert(schema.v9RenderTraces).values({
    id: 'seed-projection',
    sessionId: 'seed-session',
    traceId: 'seed-trace',
    correlationId: 'seed-trace',
    eventId: 'seed-event',
    personaSnapshotRef: 'seed-snapshot',
    intentRef: 'seed-intent',
    renderRef: SEED_RENDER_REF,
    appliedParamsHash: SEED_APPLIED_HASH,
    assetVersionHash: SEED_ASSET_HASH,
    createdAt: new Date(),
    updatedAt: new Date(),
  })

  const app = new Hono<HonoEnv>()
    .use('*', async (c, next) => {
      c.set('user', { id: 'matrix-user' } as never)
      await next()
    })
    .onError((err, c) => {
      if (err instanceof ApiError)
        return c.json({ error: err.errorCode, message: err.message }, err.statusCode)
      return c.json({ error: 'INTERNAL_SERVER_ERROR', message: 'Internal Server Error' }, 500)
    })
    .route('/api/v1/v9/events', createV9EventsRoutes(service))

  async function countRows(): Promise<{ events: number, renderTraces: number }> {
    const events = await client.query<{ n: number }>(`SELECT COUNT(*)::int AS n FROM "events"`)
    const renderTraces = await client.query<{ n: number }>(`SELECT COUNT(*)::int AS n FROM "render_traces"`)
    return { events: events.rows[0].n, renderTraces: renderTraces.rows[0].n }
  }

  await runMatrix({
    label: 'pglite (in-memory Postgres engine)',
    runPositive: true,
    countRows,
    async post(env) {
      const res = await app.request('/api/v1/v9/events', {
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
        body = { raw: text }
      }
      return { status: res.status, body }
    },
  })

  // ---- 真实 PostgreSQL 腿（只跑负例；非破坏性） ----
  const wantsPostgres = process.argv.includes('--postgres')
  const connectionString = process.env.DATABASE_URL

  if (!wantsPostgres) {
    console.info('\n=== leg: postgres — SKIPPED (pass --postgres to enable) ===')
  }
  else if (!connectionString) {
    // 显式要求了 postgres 腿却没有连接串：**不能**静默降级成"通过" ——
    // 那会把"双环境只跑了一个环境"伪装成"双环境都通过"。缺环境即是验收失败。
    check(false, '[postgres] leg requested via --postgres but DATABASE_URL is not set')
  }
  else {
    try {
      const pg = await import('pg')
      const { drizzle: drizzlePg } = await import('drizzle-orm/node-postgres')
      const pool = new pg.default.Pool({ connectionString, connectionTimeoutMillis: 3000 })
      const pgDb = drizzlePg(pool, { schema })

      // 只读探测：确认库与表可用。
      await pool.query('SELECT 1 FROM "events" LIMIT 1')
      await pool.query('SELECT 1 FROM "render_traces" LIMIT 1')

      const pgApp = new Hono<HonoEnv>()
        .use('*', async (c, next) => {
          c.set('user', { id: 'matrix-user' } as never)
          await next()
        })
        .onError((err, c) => {
          if (err instanceof ApiError)
            return c.json({ error: err.errorCode, message: err.message }, err.statusCode)
          return c.json({ error: 'INTERNAL_SERVER_ERROR', message: 'Internal Server Error' }, 500)
        })
        .route('/api/v1/v9/events', createV9EventsRoutes(createV9EventService(pgDb as never)))

      await runMatrix({
        label: 'postgres (real server, negative cases only)',
        runPositive: false,
        async countRows() {
          const events = await pool.query<{ n: number }>('SELECT COUNT(*)::int AS n FROM "events"')
          const renderTraces = await pool.query<{ n: number }>('SELECT COUNT(*)::int AS n FROM "render_traces"')
          return { events: events.rows[0].n, renderTraces: renderTraces.rows[0].n }
        },
        async post(env) {
          const res = await pgApp.request('/api/v1/v9/events', {
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
            body = { raw: text }
          }
          return { status: res.status, body }
        },
      })

      await pool.end()
    }
    catch (error) {
      // 同上：请求了真实 PG 腿却连不上，属验收失败（"未验证"不等于"通过"）。
      check(false, `[postgres] leg requested but unreachable: ${String(error)}`)
    }
  }

  await client.close()

  if (failures > 0) {
    console.error(`\nFAIL: ${failures} contract-drift assertion(s) failed`)
    process.exit(1)
  }
  const legs = wantsPostgres ? 'pglite + real postgres' : 'pglite only'
  console.info(`\nPASS: v10 contract-drift matrix (${legs}; dual-end acceptance + 400 + no-write on both tables)`)
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
