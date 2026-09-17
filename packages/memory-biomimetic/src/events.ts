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

import type { CoreStateNode } from './core-state-node'

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
  /**
   * v10 确定性排序 / 输入溯源（可选）。v9 生产者可省略；
   * `aijade.video.*` / `aijade.learning.*` 前缀的生产者【必须】提供，
   * 由 {@link assertV10RequiredFields} 强制 —— 镜像服务端
   * `v9EventEnvelopeSchema.tick` 与 `v10EventFieldsSchema.causality` 的拆分
   *（`apps/server/src/routes/v9/schema.ts:77-104`）。
   * 注意：本内核信封不引入 `origin_device` / `privacy_level` / `evidence_refs` /
   * `causal_context_refs` / `risk_score`（那是服务端信封的字段，属另一待决事项），
   * 本次只补 `tick` / `causality` 两项。
   */
  tick: z.number().int().nonnegative().optional(),
  causality: z.object({ inputHash: z.string().min(1) }).optional(),
  /**
   * v10 内生状态节点（可选，v9 可省，v10 必给）。由 {@link deriveCoreStateNode}
   * 依事件 topic + 真实控制流事实（是否真实落库）推导；是「关键事件 → S0..S8」映射的
   * 落点，回放侧可据此复算并检出漂移。沿用 `tick`/`causality` 的「可选 + 注释」风格。
   */
  core_state_node: z.string().regex(/^S[0-8]$/).optional(),
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
export const activeLearningRequestedSchema = z.strictObject({
  session_id: z.string().min(1),
  trace_id: z.string().min(1),
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
export const activeLearningCompletedSchema = z.strictObject({
  session_id: z.string().min(1),
  trace_id: z.string().min(1),
  completed_at: z.number().int().nonnegative(),
  result_ref: z.string().optional(),
  /** 与 `requested` 同源，使请求/完成可在日志里配对。 */
  quest_ref: z.string().min(1),
})
export type ActiveLearningCompletedPayload = z.infer<typeof activeLearningCompletedSchema>

export const evidenceWeaveCandidateReadySchema = z.strictObject({
  /** 事务身份。空串会被服务端 400 拒（v10 §11.1「必填字段为空串 → 400」），故此处同口径。 */
  tx_id: z.string().min(1),
  weave_id: z.string().min(1),
  /**
   * 证据图的内容身份（`graphHash()` 产出的 sha256 hex）。真实生产者恒非空 ——
   * 允许空串等于允许一条"没有图的织网"，回放一致性校验会因此失去可比对象。
   */
  graph_hash: z.string().min(1),
  candidate_memory_write_ids: z.array(z.string().min(1)),
})
export type EvidenceWeaveCandidateReadyPayload = z.infer<typeof evidenceWeaveCandidateReadySchema>

export const pgcWritePlanReadySchema = z.strictObject({
  pgc_state_id: z.string().min(1),
  write_plan_size: z.number().int().nonnegative(),
  policy_version: z.string().min(1),
})
export type PgcWritePlanReadyPayload = z.infer<typeof pgcWritePlanReadySchema>

export const memoryTxCommittedSchema = z.strictObject({
  tx_id: z.string().min(1),
  trace_id: z.string().min(1),
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
export const personaRenderRequestedSchema = z.strictObject({
  session_id: z.string().min(1),
  /** 引用人格快照（同 `PerformanceIntent.personaSnapshotRef`，§52.5）。 */
  persona_snapshot_ref: z.string().min(1),
  /** 本次请求对应的 `PerformanceIntent.id`，使 `lpm.render_ready` 可回指。 */
  intent_ref: z.string().min(1),
})
export type PersonaRenderRequestedPayload = z.infer<typeof personaRenderRequestedSchema>

/**
 * 人格表现层的**渲染回执**（具身侧 → 内核）。与 `persona.render_requested` 构成请求/回执对。
 *
 * 三个字段各承担一件事，**刻意不合并**：
 *
 * - `render_ref` —— **回指身份**。本轮回执所消费的那次请求身份，使回执与请求能一一配对。
 *   必填且 `.min(1)`：若允许缺省或空串，"回执"就退化成一行无法配对的噪声 ——
 *   而 `personaRenderRequestedSchema` 里声称的配对能力（见上）也就不可执行了。
 * - `applied_params_hash` —— **内容身份**。由 `fingerprintAppliedParams` 产出的规范化
 *   「实写通道→值」文本（键排序、`key=value`、数值定点格式化）。它的用途是回答
 *   "同一次输入是否真的写了同样的参数"，供 CBR 逐位对照。
 *   ⚠️ 它不是密码学摘要，且**空 map 时是空串**。所以它 `.min(1)` 的代价是：
 *   **"什么都没写"必须不发事件，而不是发一条空回执**（由 `buildLpmRenderReadyEvent` 强制）。
 *   与 `render_ref` 必须分开：身份在确定性回放下仍唯一，而内容指纹在低基数参数下
 *   **必然重复**，把两者合成一个字段会静默把两轮当成一轮。
 * - `asset_version_hash` —— **模型资产身份**。可选，因为它是异步解析出来的
 *   （`stage-ui` 的 `stageModelAssetVersionHash`），渲染发生时可能尚未就绪。
 *   允许 `undefined`，但**不允许空串** —— 空串会伪装成"已计算"。
 *
 * 命名沿用本文件的 snake_case 约定（见 `activeLearningRequestedSchema` 上方说明）；
 * 遥测侧的 `RenderAuditEntry` 用 camelCase，两者是**同一个概念的两个边界**，不要互抄。
 */
export const lpmRenderReadySchema = z.strictObject({
  session_id: z.string().min(1),
  render_ref: z.string().min(1),
  applied_params_hash: z.string().min(1),
  /**
   * 可选（不是"可以空"）：它在 `pef.buildLpmRenderReadyEvent` 里被显式降级 —— 空串会伪装成
   * "已计算"，故只在非空时才带上该键。HTTP 边界必须采用**同一可选性**，否则一条合法的
   * 回执（资产版本尚未异步解析出来）会在边界被 400 丢掉，而内核侧却认为它可以发出。
   */
  asset_version_hash: z.string().min(1).optional(),
})
export type LpmRenderReadyPayload = z.infer<typeof lpmRenderReadySchema>

// ============================================================================
// v10 topic payload schemas —— 字段逐字镜像服务端 `apps/server/src/routes/v9/schema.ts`
// （V9_PAYLOAD_SCHEMAS，valibot strictObject）。均使用 `z.strictObject`，未知额外字段一概拒。
// ============================================================================

export const webpageTextObservationSchema = z.strictObject({
  source_url: z.string().min(1),
  content_hash: z.string().min(1),
  spans: z.array(z.strictObject({
    start_offset: z.number().int().nonnegative(),
    end_offset: z.number().int().nonnegative(),
    label: z.string().min(1).optional(),
  })).min(1),
  observation_text: z.string().min(1),
})
export type WebpageTextObservationPayload = z.infer<typeof webpageTextObservationSchema>

export const videoTranscriptObservationSchema = z.strictObject({
  video_id: z.string().min(1),
  transcript_hash: z.string().min(1),
  time_spans: z.array(z.strictObject({
    start_ms: z.number().int().nonnegative(),
    end_ms: z.number().int().nonnegative(),
    text: z.string().min(1),
  })).min(1),
  caption_text: z.string().min(1),
})
export type VideoTranscriptObservationPayload = z.infer<typeof videoTranscriptObservationSchema>

export const learningProposedShadowParamsSchema = z.strictObject({
  session_id: z.string().min(1),
  proposal_id: z.string().min(1),
  render_ref: z.string().min(1),
  applied_params_hash: z.string().min(1),
  asset_version_hash: z.string().min(1),
  input_hash: z.string().min(1),
  candidate_params: z.record(z.string(), z.unknown()),
  confidence: z.number().min(0).max(1),
})
export type LearningProposedShadowParamsPayload = z.infer<typeof learningProposedShadowParamsSchema>

export const learningProposedEvidenceSchema = z.strictObject({
  session_id: z.string().min(1),
  proposal_id: z.string().min(1),
  render_ref: z.string().min(1),
  applied_params_hash: z.string().min(1),
  asset_version_hash: z.string().min(1),
  evidence_hash: z.string().min(1),
  claim_text: z.string().min(1),
  confidence: z.number().min(0).max(1),
})
export type LearningProposedEvidencePayload = z.infer<typeof learningProposedEvidenceSchema>

export const learningConstraintOpinionEvaluationSchema = z.strictObject({
  evaluation_target: z.string().min(1),
  claims: z.array(z.strictObject({
    claim_text: z.string().min(1),
    confidence: z.number().min(0).max(1),
  })).min(1),
  uncertainty_notes: z.string().min(1),
})
export type LearningConstraintOpinionEvaluationPayload = z.infer<typeof learningConstraintOpinionEvaluationSchema>

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
export const webpageTextObservationEvent = topicEvent('aijade.video.observation.webpage_text', webpageTextObservationSchema)
export const videoTranscriptObservationEvent = topicEvent('aijade.video.observation.video_transcript', videoTranscriptObservationSchema)
export const learningProposedShadowParamsEvent = topicEvent('aijade.learning.proposed.shadow_params', learningProposedShadowParamsSchema)
export const learningProposedEvidenceEvent = topicEvent('aijade.learning.proposed.evidence', learningProposedEvidenceSchema)
export const learningConstraintOpinionEvaluationEvent = topicEvent('aijade.learning.constraint.opinion_evaluation', learningConstraintOpinionEvaluationSchema)

/** 全部受支持 topic 的判别联合。新增 topic 必须在此登记，否则 `safeParse` 会拒。 */
export const aijadeEventSchema = z.union([
  activeLearningRequestedEvent,
  activeLearningCompletedEvent,
  evidenceWeaveCandidateReadyEvent,
  pgcWritePlanReadyEvent,
  memoryTxCommittedEvent,
  personaRenderRequestedEvent,
  lpmRenderReadyEvent,
  webpageTextObservationEvent,
  videoTranscriptObservationEvent,
  learningProposedShadowParamsEvent,
  learningProposedEvidenceEvent,
  learningConstraintOpinionEvaluationEvent,
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
  'aijade.video.observation.webpage_text',
  'aijade.video.observation.video_transcript',
  'aijade.learning.proposed.shadow_params',
  'aijade.learning.proposed.evidence',
  'aijade.learning.constraint.opinion_evaluation',
] as const
export type AijadeTopic = typeof AIJADE_TOPICS[number]

/** 校验一个事件是否合规；返回窄化后的事件或错误。供事件边界处调用。 */
export function parseAijadeEvent(input: unknown): AijadeEvent {
  return aijadeEventSchema.parse(input)
}

export function safeParseAijadeEvent(input: unknown) {
  return aijadeEventSchema.safeParse(input)
}

/**
 * v10 确定性/溯源强制校验 —— 镜像 `apps/server/src/routes/v9/events.ts` 的前缀检查。
 *
 * v9 生产者可省略 `tick` / `causality`；但凡 `aijade.video.*` 或 `aijade.learning.*`
 * 前缀的事件【必须】同时携带 `tick`（int≥0）与 `causality.inputHash`（非空串），
 * 否则视为不合规并抛错。这样内核与 HTTP 边界口径一致：v10 事件若无这两项，
 * 在两边都不会被接受。
 */
export function assertV10RequiredFields(event: AijadeEvent): void {
  if (event.topic.startsWith('aijade.video.') || event.topic.startsWith('aijade.learning.')) {
    if (
      event.tick === undefined
      || event.causality === undefined
      || event.causality.inputHash === ''
    ) {
      throw new Error('v10 video/learning events require tick and causality.inputHash')
    }
  }
}

/** v10 工厂统一的信封形态（在 v9 信封基础上允许可选的 tick / causality）。 */
export interface V10EventEnvelope {
  event_id: string
  trace_id: string
  correlation_id: string
  timestamp: number
  producer: string
  idempotency_key: string
  replay_mode: 'live' | 'replay'
  risk_level: RiskLevel
  tick?: number
  causality?: { inputHash: string }
  /** v10 内生状态节点（S0..S8），由 `deriveCoreStateNode` 决定。 */
  core_state_node?: CoreStateNode
}

function buildV10Event(
  eventSchema: z.ZodTypeAny,
  topic: AijadeTopic,
  payload: unknown,
  envelope: V10EventEnvelope,
) {
  const event = eventSchema.parse({ ...envelope, topic, payload }) as AijadeEvent
  assertV10RequiredFields(event)
  return event
}

/** 构造 aijade.video.observation.webpage_text 事件（已 zod 校验；缺 tick/causality 即抛错）。 */
export function buildWebpageTextObservationEvent(payload: WebpageTextObservationPayload, envelope: V10EventEnvelope) {
  return buildV10Event(webpageTextObservationEvent, 'aijade.video.observation.webpage_text', payload, envelope)
}

/** 构造 aijade.video.observation.video_transcript 事件（已 zod 校验；缺 tick/causality 即抛错）。 */
export function buildVideoTranscriptObservationEvent(payload: VideoTranscriptObservationPayload, envelope: V10EventEnvelope) {
  return buildV10Event(videoTranscriptObservationEvent, 'aijade.video.observation.video_transcript', payload, envelope)
}

/** 构造 aijade.learning.proposed.shadow_params 事件（已 zod 校验；缺 tick/causality 即抛错）。 */
export function buildLearningProposedShadowParamsEvent(payload: LearningProposedShadowParamsPayload, envelope: V10EventEnvelope) {
  return buildV10Event(learningProposedShadowParamsEvent, 'aijade.learning.proposed.shadow_params', payload, envelope)
}

/** 构造 aijade.learning.proposed.evidence 事件（已 zod 校验；缺 tick/causality 即抛错）。 */
export function buildLearningProposedEvidenceEvent(payload: LearningProposedEvidencePayload, envelope: V10EventEnvelope) {
  return buildV10Event(learningProposedEvidenceEvent, 'aijade.learning.proposed.evidence', payload, envelope)
}

/** 构造 aijade.learning.constraint.opinion_evaluation 事件（已 zod 校验；缺 tick/causality 即抛错）。 */
export function buildLearningConstraintOpinionEvaluationEvent(payload: LearningConstraintOpinionEvaluationPayload, envelope: V10EventEnvelope) {
  return buildV10Event(learningConstraintOpinionEvaluationEvent, 'aijade.learning.constraint.opinion_evaluation', payload, envelope)
}
