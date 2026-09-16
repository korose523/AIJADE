import {
  array,
  integer,
  minLength,
  minValue,
  number,
  object,
  optional,
  picklist,
  pipe,
  record,
  strictObject,
  string,
  unknown as vUnknown,
} from 'valibot'

/**
 * v9 事件信封 + **逐 topic payload** 的服务端校验 schema（valibot）。
 *
 * 真源：`packages/memory-biomimetic/src/events.ts` 的 `aijadeEventSchema`（zod v4）。
 * 本仓 `apps/` 不依赖研究内核（三层隔离，见 `PROVENANCE.md`），故此处**有意复制**
 * envelope + topic + payload 约束，而不是 import 内核。
 *
 * ⚠️ 为什么必须有逐 topic 的 payload 校验（这是踩出来的坑，勿回退）
 *
 * 早期本边界只校验 envelope，`payload` 以 `record(string(), unknown)` 透传。后果是：
 * 内核要求 `persona.render_requested` 必填 `persona_snapshot_ref` + `intent_ref`
 * （`events.ts:142/144`），而 `stage-ui` 实际发的是 `{ session_id, request_ref }`
 * 且 `request_ref` 的值就是 `trace_id` 自身 —— 一个完全不同且不合规的形状。
 * 因为透传，它照样入库 201，"同 trace 配对"照样成立，
 * 于是出现 **"配对成功 ≠ 因果成立"**：库里能反查到两条同 trace 事件，
 * 但背后并没有人格快照、也没有 PerformanceIntent 可被回指。
 * 更糟的是原先 `verify-v9-events-http.ts` 的 happy path 直接抄了那个错误形状，
 * 于是把这次漂移当成"已验证通过"钉进了测试。
 *
 * 所以本文件现在对每个 topic 做**严格**（strict）校验：
 * 缺字段 / 空串 / 类型不符 / **出现未知字段** 一律 400，且**不写入 events**。
 * "未知字段"必须拒 —— 否则靠加一个字段就能绕过契约。
 *
 * 复制带来的漂移风险由以下机制兜底：
 * - `V9_PAYLOAD_SCHEMAS` 的键必须覆盖 `AIJADE_TOPICS` 全集中每一 topic；新增 topic 时
 *   两处都要加，缺失会在路由处显式抛错（而不是悄悄放行）。
 * - topic payload 的字段名/必填性与内核 zod schema 一一对应；任一改动都应同步两处。
 *
 * ⚠️ 不在服务端重算 `applied_params_hash`：客户端是"实写"的唯一目击者，服务端重算会
 *   引入双实现漂移（见 Step B 设计稿 §2 / §6）。
 * ⚠️ 不在这里复刻业务不变量（例如 `resource_budget.spent <= allocated`）：那是策略层的
 *   事，留在内核，避免第三份"同一规则"的实现。本边界只保证**可追溯性所需的最小形状**。
 */
export const AIJADE_TOPICS = [
  'aijade.active_learning.requested',
  'aijade.active_learning.completed',
  'aijade.evidence.weave_candidate_ready',
  'aijade.pgc.write_plan_ready',
  'aijade.memory_tx.committed',
  'aijade.persona.render_requested',
  'aijade.lpm.render_ready',
] as const

export type AijadeTopic = (typeof AIJADE_TOPICS)[number]

export const v9EventEnvelopeSchema = object({
  event_id: pipe(string(), minLength(1)),
  trace_id: pipe(string(), minLength(1)),
  correlation_id: pipe(string(), minLength(1)),
  /** 内核信封用 number（unix ms）。服务端只做非负整数校验，再 `new Date()` 落库。 */
  timestamp: pipe(number(), integer(), minValue(0)),
  producer: pipe(string(), minLength(1)),
  /** 幂等键：承担去重，不是 event_id（event_id 只保证全局不撞）。 */
  idempotency_key: pipe(string(), minLength(1)),
  replay_mode: picklist(['live', 'replay']),
  risk_level: picklist(['low', 'medium', 'high']),
  topic: picklist(AIJADE_TOPICS),
  /** 不再透传：命中 topic 后由 {@link V9_PAYLOAD_SCHEMAS} 做语义校验。 */
  payload: record(string(), vUnknown()),
})

const nonNegInt = pipe(number(), integer(), minValue(0))

/** 每个 topic 的 payload schema —— 字段名与必填性镜像内核 `events.ts`。 */
export const V9_PAYLOAD_SCHEMAS = {
  'aijade.active_learning.requested': strictObject({
    session_id: string(),
    trace_id: string(),
    requested_at: nonNegInt,
    target: optional(string()),
    /** 指向 `contracts-v8.LearningQuest.id`，使预算/停止条件可回查到活真源。 */
    quest_ref: pipe(string(), minLength(1)),
    resource_budget: strictObject({
      allocated: pipe(number(), minValue(0)),
      spent: pipe(number(), minValue(0)),
      unit: picklist(['queries', 'minutes', 'usd', 'tokens']),
    }),
    /** 非空停止条件：禁止"无终点浏览"在结构上可表达。 */
    stop_conditions: pipe(array(pipe(string(), minLength(1))), minLength(1)),
  }),
  'aijade.active_learning.completed': strictObject({
    session_id: string(),
    trace_id: string(),
    completed_at: nonNegInt,
    result_ref: optional(string()),
    /** 与 requested 同源，使请求/完成可在日志里配对。 */
    quest_ref: pipe(string(), minLength(1)),
  }),
  'aijade.evidence.weave_candidate_ready': strictObject({
    tx_id: string(),
    weave_id: string(),
    graph_hash: string(),
    candidate_memory_write_ids: array(string()),
  }),
  'aijade.pgc.write_plan_ready': strictObject({
    pgc_state_id: string(),
    write_plan_size: nonNegInt,
    policy_version: string(),
  }),
  'aijade.memory_tx.committed': strictObject({
    tx_id: string(),
    trace_id: string(),
    committed_count: nonNegInt,
    rejected_count: nonNegInt,
    throttled_count: nonNegInt,
  }),
  /**
   * 请求侧两条引用是"人格快照—意图—渲染"因果链能被反查的**唯一依据**：
   * - `persona_snapshot_ref`：本次渲染所依据的人格快照，必须与
   *   `contracts-v8.PerformanceIntent.personaSnapshotRef` 同源同值；
   * - `intent_ref`：本次请求对应的 `PerformanceIntent.id`，是回执 `render_ref` 的回指目标。
   *
   * 允许它们缺失或空，就等于允许"一条无法证明忠于任何意图的渲染"，
   * 那时同 trace 配对只是噪音。故二者均必填非空。
   */
  'aijade.persona.render_requested': strictObject({
    session_id: string(),
    persona_snapshot_ref: pipe(string(), minLength(1)),
    intent_ref: pipe(string(), minLength(1)),
  }),
  /**
   * 回执侧三字段各司其职，**刻意不合并**：身份 / 内容指纹 / 资产版本。
   * `applied_params_hash` 要求非空 —— 空 map 时应"不发事件"，
   * 而不是发一条空回执（由内核 `buildLpmRenderReadyEvent` 强制）。
   */
  'aijade.lpm.render_ready': strictObject({
    session_id: pipe(string(), minLength(1)),
    render_ref: pipe(string(), minLength(1)),
    applied_params_hash: pipe(string(), minLength(1)),
    /** 可选但**不允许空串**：空串会伪装成"已计算"。 */
    asset_version_hash: optional(pipe(string(), minLength(1))),
  }),
} as const satisfies Record<AijadeTopic, unknown>

/** 保证覆盖检查不会因为类型层面的遗漏而静默通过。 */
export const V9_TOPICS_WITHOUT_PAYLOAD_SCHEMA = AIJADE_TOPICS.filter(
  t => !(t in V9_PAYLOAD_SCHEMAS),
)
