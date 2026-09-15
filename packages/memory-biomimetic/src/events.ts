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

export const activeLearningRequestedSchema = z.object({
  session_id: z.string(),
  trace_id: z.string(),
  requested_at: z.number().int().nonnegative(),
  target: z.string().optional(),
})
export type ActiveLearningRequestedPayload = z.infer<typeof activeLearningRequestedSchema>

export const activeLearningCompletedSchema = z.object({
  session_id: z.string(),
  trace_id: z.string(),
  completed_at: z.number().int().nonnegative(),
  result_ref: z.string().optional(),
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

export const personaRenderRequestedSchema = z.object({
  session_id: z.string(),
  persona_ref: z.string().optional(),
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
