/**
 * v9 统一事件信封 + topic schema（AIJADE 事件总线契约）。
 *
 * 设计约束（来自 v9 规范 / 上游 AIRI 事件契约精神）：
 * - 所有跨模块事件共用**同一个信封形状**，便于单一消费者、单一幂等键、单一回放语义。
 * - `idempotency_key` 必填且唯一：这是 `events` 表唯一约束的对应字段，也是
 *   MemoryTx「同一 tx 重复提交应幂等」的落点——事件层用同一把 key 去重。
 * - `replay_mode` 区分 live / replay，回放校验时必须为 `replay` 才能被一致性校验接受。
 * - `risk_level` 让高风险记忆写入（persona / 高 intensity）在流水线里可被单独路由/审计。
 *
 * 用 zod（项目已在用 zod v4）做运行时校验，而不仅仅是 TS 类型——因为事件来自
 * 网络/跨进程边界，必须在边界处校验，不能信赖调用方的类型。
 */

import { z } from 'zod'

/** 风险等级：写入门控用它给记忆写做路由/审计分级。 */
export const riskLevelSchema = z.enum(['low', 'medium', 'high'])
export type RiskLevel = z.infer<typeof riskLevelSchema>

/** live=真实发生；replay=回放/校验。回放一致性校验只允许 replay_mode='replay' 进入。 */
export const replayModeSchema = z.enum(['live', 'replay'])
export type ReplayMode = z.infer<typeof replayModeSchema>

/** 信封字段（除 topic/payload 外的所有字段）。被每个 topic 事件复用。 */
const envelopeFields = {
  event_id: z.string().min(1),
  trace_id: z.string().min(1),
  correlation_id: z.string().min(1),
  timestamp: z.number().int().nonnegative(),
  producer: z.string().min(1),
  idempotency_key: z.string().min(1),
  replay_mode: replayModeSchema,
  risk_level: riskLevelSchema,
} as const

/** 统一事件信封（topic 与 payload 为 unknown 的宽松形态，供总线透传）。 */
export const eventEnvelopeSchema = z.object({
  ...envelopeFields,
  topic: z.string().min(1),
  payload: z.unknown(),
})
export type AijadeEventEnvelope = z.infer<typeof eventEnvelopeSchema>

// ============================================================================
// Topic payload schemas
// ============================================================================

/**
 * 一个**已被界定（bounded）**的学习任务的启动请求。
 *
 * 为什么 `resource_budget` 与 `stop_conditions` 是**必填**：v8 §48.2 要求「每个学习任务
 * 必须在开始前被界定」且「禁止无终点浏览」。把它们设成必填，是让"无预算 / 无停止条件
 * 的请求"**不可表达**，而不是靠调用方自觉——于是"有请求必有界"由 schema 保证，可以在
 * 事件日志上直接审计（这正是事件层存在的意义）。
 *
 * 语义边界：`resource_budget` 与 `stop_conditions` 是**发出时刻的不可变快照**，活真源仍是
 * `contracts-v8.LearningQuest`（由 `validateLearningQuest` 校验）。此处记录快照是为了让
 * 回放/审计不必回查可变的 quest 行，而不是制造第二套活真源。
 *
 * 命名约定：本文件 payload 用 snake_case（与既有 topic 一致）；`contracts-v8.ts` 侧用
 * camelCase。这个差异是有意的，不要"统一"掉。
 */
export const activeLearningRequestedSchema = z.object({
  session_id: z.string(),
  trace_id: z.string(),
  requested_at: z.number().int().nonnegative(),
  target: z.string().optional(),
  /** 指向 `contracts-v8.LearningQuest.id`（活真源）。 */
  quest_ref: z.string().min(1),
  /** 资源预算快照，必须 allocated ≥ spent（v8 §48.2）。 */
  resource_budget: z.object({
    allocated: z.number().nonnegative(),
    spent: z.number().nonnegative(),
    unit: z.enum(['queries', 'minutes', 'usd', 'tokens']),
  }).refine(b => b.spent <= b.allocated, {
    message: 'resource_budget.spent 不得超过 allocated（v8 §48.2 预算必须可界定）',
  }),
  /** 停止条件，必须非空（v8 §48.2 禁止无终点浏览）。 */
  stop_conditions: z.array(z.string().min(1)).min(1),
})
export type ActiveLearningRequestedPayload = z.infer<typeof activeLearningRequestedSchema>

/**
 * 学习任务**走完流水线**的完成回执。
 *
 * 只在 quest 真正走完时发（`ael.ts` 的完成边），**不**在 `FAILED` / `ABANDONED` 时发——
 * 把"完成"与"中止"分开，否则这个事件名会说谎，下游也就无法用"有 completed"当作
 * 学习量已产出的证据。
 */
export const activeLearningCompletedSchema = z.object({
  session_id: z.string(),
  trace_id: z.string(),
  completed_at: z.number().int().nonnegative(),
  result_ref: z.string().optional(),
  /** 与 `requested` 同源，使请求/完成可在日志里配对。 */
  quest_ref: z.string().min(1),
})
export type ActiveLearningCompletedPayload = z.infer<typeof activeLearningCompletedSchema>

export const evidenceWeaveCandidateReadySchema = z.object({
  tx_id: z.string(),
  weave_id: z.string(),
  graph_hash: z.string(),
  candidate_memory_write_ids: z.array(z.string()),
})
export type EvidenceWeaveCandidateReadyPayload = z.infer<typeof evidenceWeaveCandidateReadySchema>

export const pgcWritePlanReadySchema = z.object({
  pgc_state_id: z.string(),
  write_plan_size: z.number().int().nonnegative(),
  policy_version: z.string(),
})
export type PgcWritePlanReadyPayload = z.infer<typeof pgcWritePlanReadySchema>

export const memoryTxCommittedSchema = z.object({
  tx_id: z.string(),
  trace_id: z.string(),
  committed_count: z.number().int().nonnegative(),
  rejected_count: z.number().int().nonnegative(),
  throttled_count: z.number().int().nonnegative(),
})
export type MemoryTxCommittedPayload = z.infer<typeof memoryTxCommittedSchema>

/**
 * 人格表现层的渲染请求（内核 → 具身侧）。与 `lpm.render_ready` 构成请求/回执对。
 *
 * 两个引用都是**必填**，理由是 v8 §52.5「身份连续性可审计」：
 * - `persona_snapshot_ref` 与 `contracts-v8.PerformanceIntent.personaSnapshotRef` **同源同值**。
 *   人格快照只在记忆提交之后才存在（v9 §6.1 因果链：PGC/MemoryTx → 长期记忆 → PersonalityLPM），
 *   所以"先渲染再补身份"这种顺序在契约上就被排除掉。
 * - `intent_ref` 是本次请求对应的 `PerformanceIntent.id`。有了它，具身侧回的
 *   `lpm.render_ready.render_ref` 才能回指到"究竟渲染了哪一次意图"，否则那条回执无法与
 *   请求配对，链条在审计上是断的。
 *
 * 更名为 `persona_snapshot_ref`（原字段为可选 `persona_ref`）：后者语义含糊且可省略，
 * 与 §52.5 冲突，故不保留为第二个字段以免出现两套引用写法。
 */
export const personaRenderRequestedSchema = z.object({
  session_id: z.string(),
  /** 引用人格快照（同 `PerformanceIntent.personaSnapshotRef`，§52.5）。 */
  persona_snapshot_ref: z.string().min(1),
  /** 本次请求对应的 `PerformanceIntent.id`，使 `lpm.render_ready` 可回指。 */
  intent_ref: z.string().min(1),
})
export type PersonaRenderRequestedPayload = z.infer<typeof personaRenderRequestedSchema>

export const lpmRenderReadySchema = z.object({
  session_id: z.string(),
  render_ref: z.string().optional(),
})
export type LpmRenderReadyPayload = z.infer<typeof lpmRenderReadySchema>

// ============================================================================
// 每个 topic 一个强类型事件（信封 + 字面量 topic + 强类型 payload）
// ============================================================================

function topicEvent<K extends string>(topic: K, payload: z.ZodTypeAny) {
  return z.object({ ...envelopeFields, topic: z.literal(topic), payload })
}

export const activeLearningRequestedEvent = topicEvent('aijade.active_learning.requested', activeLearningRequestedSchema)
export const activeLearningCompletedEvent = topicEvent('aijade.active_learning.completed', activeLearningCompletedSchema)
export const evidenceWeaveCandidateReadyEvent = topicEvent('aijade.evidence.weave_candidate_ready', evidenceWeaveCandidateReadySchema)
export const pgcWritePlanReadyEvent = topicEvent('aijade.pgc.write_plan_ready', pgcWritePlanReadySchema)
export const memoryTxCommittedEvent = topicEvent('aijade.memory_tx.committed', memoryTxCommittedSchema)
export const personaRenderRequestedEvent = topicEvent('aijade.persona.render_requested', personaRenderRequestedSchema)
export const lpmRenderReadyEvent = topicEvent('aijade.lpm.render_ready', lpmRenderReadySchema)

/** 全部受支持 topic 的判别联合。新增 topic 必须在此登记，否则 `safeParse` 会拒。 */
export const aijadeEventSchema = z.union([
  activeLearningRequestedEvent,
  activeLearningCompletedEvent,
  evidenceWeaveCandidateReadyEvent,
  pgcWritePlanReadyEvent,
  memoryTxCommittedEvent,
  personaRenderRequestedEvent,
  lpmRenderReadyEvent,
])
export type AijadeEvent = z.infer<typeof aijadeEventSchema>

/** 受支持的 topic 字面量集合（用于文档/校验）。 */
export const AIJADE_TOPICS = [
  'aijade.active_learning.requested',
  'aijade.active_learning.completed',
  'aijade.evidence.weave_candidate_ready',
  'aijade.pgc.write_plan_ready',
  'aijade.memory_tx.committed',
  'aijade.persona.render_requested',
  'aijade.lpm.render_ready',
] as const
export type AijadeTopic = typeof AIJADE_TOPICS[number]

/** 校验一个事件是否合规；返回窄化后的事件或错误。供事件边界处调用。 */
export function parseAijadeEvent(input: unknown): AijadeEvent {
  return aijadeEventSchema.parse(input)
}

export function safeParseAijadeEvent(input: unknown) {
  return aijadeEventSchema.safeParse(input)
}
