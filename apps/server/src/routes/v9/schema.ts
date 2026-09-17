import {
  array,
  integer,
  maxValue,
  minLength,
  minValue,
  number,
  optional,
  picklist,
  pipe,
  record,
  regex,
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
  'aijade.video.observation.webpage_text',
  'aijade.video.observation.video_transcript',
  'aijade.learning.proposed.shadow_params',
  'aijade.learning.proposed.evidence',
  'aijade.learning.constraint.opinion_evaluation',
] as const

export type AijadeTopic = (typeof AIJADE_TOPICS)[number]

const nonNegInt = pipe(number(), integer(), minValue(0))

/**
 * v10 protocol additions. Kept optional so existing v9 producers can migrate
 * without changing the v9 endpoint; v10 producers must send both fields.
 */
const v10CausalitySchema = strictObject({
  inputHash: pipe(string(), minLength(1)),
})

export const v9EventEnvelopeSchema = strictObject({
  event_id: pipe(string(), minLength(1)),
  trace_id: pipe(string(), minLength(1)),
  correlation_id: pipe(string(), minLength(1)),
  /** 内核信封用 number（unix ms）。服务端只做非负整数校验，再 `new Date()` 落库。 */
  timestamp: pipe(number(), integer(), minValue(0)),
  producer: pipe(string(), minLength(1)),
  origin_device: pipe(string(), minLength(1)),
  privacy_level: picklist([0, 1, 2, 3]),
  evidence_refs: array(string()),
  causal_context_refs: array(string()),
  risk_score: pipe(number(), minValue(0), maxValue(1)),
  /** 幂等键：承担去重，不是 event_id（event_id 只保证全局不撞）。 */
  idempotency_key: pipe(string(), minLength(1)),
  replay_mode: picklist(['live', 'replay']),
  risk_level: picklist(['low', 'medium', 'high']),
  /** v10 deterministic ordering and input provenance (optional for v9 clients). */
  tick: optional(nonNegInt),
  causality: optional(v10CausalitySchema),
  /** v10 内生状态节点（S0..S8）；optional 以兼容旧客户端（strictObject 下客户端多发也必须登记）。 */
  core_state_node: optional(pipe(string(), regex(/^S[0-8]$/))),
  topic: picklist(AIJADE_TOPICS),
  /** 不再透传：命中 topic 后由 {@link V9_PAYLOAD_SCHEMAS} 做语义校验。 */
  payload: record(string(), vUnknown()),
})

export const v10EventFieldsSchema = strictObject({
  tick: nonNegInt,
  causality: v10CausalitySchema,
})

/** 回放一致性校验请求体：按 `tick` + `causality.inputHash` 定位同一输入快照下的事件。 */
export const v9ReplaySchema = strictObject({
  tick: nonNegInt,
  inputHash: pipe(string(), minLength(1)),
})

/** 每个 topic 的 payload schema —— 字段名与必填性镜像内核 `events.ts`。 */
export const V9_PAYLOAD_SCHEMAS = {
  'aijade.active_learning.requested': strictObject({
    session_id: pipe(string(), minLength(1)),
    trace_id: pipe(string(), minLength(1)),
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
    session_id: pipe(string(), minLength(1)),
    trace_id: pipe(string(), minLength(1)),
    completed_at: nonNegInt,
    result_ref: optional(string()),
    /** 与 requested 同源，使请求/完成可在日志里配对。 */
    quest_ref: pipe(string(), minLength(1)),
  }),
  /**
   * `graph_hash` 是证据图的内容身份（`graphHash()` 的 sha256 hex），真实生产者恒非空。
   * 此处**必须** `minLength(1)`：空串曾被接受并落库（见 `verify-v10-contract-drift.ts`
   * 的 `blank graph_hash` 负例），等于允许一条没有图的织网 —— v10 §11.1 要求空串一律 400。
   */
  'aijade.evidence.weave_candidate_ready': strictObject({
    tx_id: pipe(string(), minLength(1)),
    weave_id: pipe(string(), minLength(1)),
    graph_hash: pipe(string(), minLength(1)),
    candidate_memory_write_ids: array(pipe(string(), minLength(1))),
  }),
  'aijade.pgc.write_plan_ready': strictObject({
    pgc_state_id: pipe(string(), minLength(1)),
    write_plan_size: nonNegInt,
    policy_version: pipe(string(), minLength(1)),
  }),
  'aijade.memory_tx.committed': strictObject({
    tx_id: pipe(string(), minLength(1)),
    trace_id: pipe(string(), minLength(1)),
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
    session_id: pipe(string(), minLength(1)),
    persona_snapshot_ref: pipe(string(), minLength(1)),
    intent_ref: pipe(string(), minLength(1)),
  }),
  /**
   * 回执侧三字段各司其职，**刻意不合并**：身份 / 内容指纹 / 资产版本。
   * `applied_params_hash` 要求非空 —— 空 map 时应"不发事件"，
   * 而不是发一条空回执（由内核 `buildLpmRenderReadyEvent` 强制）。
   *
   * `asset_version_hash` 是 **optional 而非必填**，与内核 `lpmRenderReadySchema` 同口径：
   * 它是异步解析出来的（`stage-ui` 的 `stageModelAssetVersionHash`），渲染发生时可能尚未就绪，
   * 内核侧会把它显式降级为"不带该键"。若边界强制必填，一条合法的回执会被 400 丢掉，
   * 而请求侧 `persona.render_requested` 已落库 ⇒ 配对缺口被凭空制造出来。
   * 注意"可选"不等于"可空"：给了就必须非空。
   */
  'aijade.lpm.render_ready': strictObject({
    session_id: pipe(string(), minLength(1)),
    render_ref: pipe(string(), minLength(1)),
    applied_params_hash: pipe(string(), minLength(1)),
    asset_version_hash: optional(pipe(string(), minLength(1))),
  }),
  'aijade.video.observation.webpage_text': strictObject({
    source_url: pipe(string(), minLength(1)),
    content_hash: pipe(string(), minLength(1)),
    spans: pipe(array(strictObject({
      start_offset: nonNegInt,
      end_offset: nonNegInt,
      label: optional(pipe(string(), minLength(1))),
    })), minLength(1)),
    observation_text: pipe(string(), minLength(1)),
  }),
  'aijade.video.observation.video_transcript': strictObject({
    video_id: pipe(string(), minLength(1)),
    transcript_hash: pipe(string(), minLength(1)),
    time_spans: pipe(array(strictObject({
      start_ms: nonNegInt,
      end_ms: nonNegInt,
      text: pipe(string(), minLength(1)),
    })), minLength(1)),
    caption_text: pipe(string(), minLength(1)),
  }),
  'aijade.learning.proposed.shadow_params': strictObject({
    session_id: pipe(string(), minLength(1)),
    proposal_id: pipe(string(), minLength(1)),
    render_ref: pipe(string(), minLength(1)),
    applied_params_hash: pipe(string(), minLength(1)),
    asset_version_hash: pipe(string(), minLength(1)),
    input_hash: pipe(string(), minLength(1)),
    candidate_params: record(string(), vUnknown()),
    confidence: pipe(number(), minValue(0), maxValue(1)),
  }),
  'aijade.learning.proposed.evidence': strictObject({
    session_id: pipe(string(), minLength(1)),
    proposal_id: pipe(string(), minLength(1)),
    render_ref: pipe(string(), minLength(1)),
    applied_params_hash: pipe(string(), minLength(1)),
    asset_version_hash: pipe(string(), minLength(1)),
    evidence_hash: pipe(string(), minLength(1)),
    claim_text: pipe(string(), minLength(1)),
    confidence: pipe(number(), minValue(0), maxValue(1)),
  }),
  'aijade.learning.constraint.opinion_evaluation': strictObject({
    evaluation_target: pipe(string(), minLength(1)),
    claims: pipe(array(strictObject({
      claim_text: pipe(string(), minLength(1)),
      confidence: pipe(number(), minValue(0), maxValue(1)),
    })), minLength(1)),
    uncertainty_notes: pipe(string(), minLength(1)),
  }),
} as const satisfies Record<AijadeTopic, unknown>

/** 保证覆盖检查不会因为类型层面的遗漏而静默通过。 */
export const V9_TOPICS_WITHOUT_PAYLOAD_SCHEMA = AIJADE_TOPICS.filter(
  t => !(t in V9_PAYLOAD_SCHEMAS),
)

export const v9PerceptionSchema = strictObject({
  event_id: pipe(string(), minLength(1)),
  session_id: pipe(string(), minLength(1)),
  trace_id: pipe(string(), minLength(1)),
  correlation_id: pipe(string(), minLength(1)),
  timestamp: pipe(number(), integer(), minValue(0)),
  origin_device: pipe(string(), minLength(1)),
  privacy_level: picklist([0, 1, 2, 3]),
  risk_score: pipe(number(), minValue(0)),
  source: pipe(string(), minLength(1)),
  content: pipe(string(), minLength(1)),
  stimulus_features: optional(record(string(), number())),
  risk_level: optional(picklist(['low', 'medium', 'high'])),
})
