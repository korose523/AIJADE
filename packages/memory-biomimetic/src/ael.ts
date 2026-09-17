import type { LearningQuest, SourceRecord } from './contracts-v8'
import type { AijadeEventEnvelope } from './events'

import { validateLearningQuest } from './contracts-v8'
import { activeLearningCompletedEvent, activeLearningRequestedEvent } from './events'

/**
 * v8 §48 — AEL: Autonomous Epistemic Learning.
 *
 * AEL turns "search → summarise" into a bounded, evidence-graded learning loop:
 * every quest declares stop conditions up front (no endless browsing), external
 * content is quarantined before it can influence beliefs, source lineage is kept
 * so reposts of one origin cannot masquerade as multi-source validation, and
 * conclusions are graded by evidence quality rather than by vote.
 *
 * Pure and deterministic; runtime wiring (budgets, consent) lives in the store /
 * config layer, like the v7 mechanisms.
 */

// ---------------------------------------------------------------------------
// §48.1 — the learning-quest state machine
// ---------------------------------------------------------------------------

/** The 14 pipeline stages (§48.1). */
export const QUEST_PIPELINE = [
  'OBSERVE',
  'FORM_QUESTION',
  'SCOPE_AND_BUDGET',
  'PLAN_SOURCES',
  'SEARCH',
  'ACQUIRE',
  'EXTRACT_CLAIMS',
  'CROSS_VALIDATE',
  'SYNTHESIZE',
  'TEST_OR_PRACTICE',
  'CONSOLIDATE',
  'TRANSFER_PROBE',
  'SHARE_OR_INCUBATE',
  'REFLECT',
] as const

export type QuestPipelineStage = typeof QUEST_PIPELINE[number]

/** Exceptional / terminal states any stage may enter (§48.1). */
export type QuestExceptionalStage = 'PAUSED' | 'NEEDS_USER_CONSENT' | 'CONTRADICTED' | 'FAILED' | 'ABANDONED'

export type QuestStage = QuestPipelineStage | QuestExceptionalStage

export type QuestEvent
  = | 'advance' // move to the next pipeline stage
    | 'pause' // park the quest (resumable)
    | 'resume' // return from PAUSED / NEEDS_USER_CONSENT / CONTRADICTED
    | 'need_consent' // pause pending user consent
    | 'grant_consent' // consent granted → resume
    | 'contradict' // a contradiction was found (resumable after resolution)
    | 'fail' // unrecoverable failure (terminal)
    | 'abandon' // deliberately drop (terminal)

/** Full quest state: the current stage plus where to resume from. */
export interface QuestState {
  stage: QuestStage
  /** The active stage to return to after an exceptional state. */
  resumePoint?: QuestPipelineStage
}

const TERMINAL: ReadonlySet<QuestStage> = new Set(['FAILED', 'ABANDONED'])
const RESUMABLE: ReadonlySet<QuestStage> = new Set(['PAUSED', 'NEEDS_USER_CONSENT', 'CONTRADICTED'])

/**
 * §48.1 — quest state machine. Returns the next state, or null for an illegal
 * event from the current state (so illegal lifecycle jumps are recorded, not
 * silently applied). `REFLECT` is the final pipeline stage; `advance` from it
 * completes the quest (returns null because there is no further state).
 */
export function transitionQuest(state: QuestState, event: QuestEvent): QuestState | null {
  // Terminal states accept no further events.
  if (TERMINAL.has(state.stage))
    return null

  const isPipeline = (QUEST_PIPELINE as readonly string[]).includes(state.stage)

  switch (event) {
    case 'advance': {
      if (!isPipeline)
        return null
      const idx = QUEST_PIPELINE.indexOf(state.stage as QuestPipelineStage)
      if (idx === QUEST_PIPELINE.length - 1)
        return null // REFLECT is the last stage; advancing completes the quest
      return { stage: QUEST_PIPELINE[idx + 1] }
    }
    case 'pause':
      if (!isPipeline)
        return null
      return { stage: 'PAUSED', resumePoint: state.stage as QuestPipelineStage }
    case 'need_consent':
      if (!isPipeline)
        return null
      return { stage: 'NEEDS_USER_CONSENT', resumePoint: state.stage as QuestPipelineStage }
    case 'contradict':
      if (!isPipeline)
        return null
      return { stage: 'CONTRADICTED', resumePoint: state.stage as QuestPipelineStage }
    case 'resume':
    case 'grant_consent': {
      if (!RESUMABLE.has(state.stage))
        return null
      if (event === 'grant_consent' && state.stage !== 'NEEDS_USER_CONSENT')
        return null
      if (!state.resumePoint)
        return null
      return { stage: state.resumePoint }
    }
    case 'fail':
      return { stage: 'FAILED' }
    case 'abandon':
      return { stage: 'ABANDONED' }
  }
}

// ---------------------------------------------------------------------------
// §48.2 — lifecycle edges → 统一事件协议（v9 §3）
// ---------------------------------------------------------------------------

/**
 * `active_learning.requested` 的**唯一**发射边：离开 `SCOPE_AND_BUDGET`。
 *
 * 为什么是这条边（对"进入 FORM_QUESTION / 两处都发 / 只在 SCOPE_AND_BUDGET 发"三选的定论）：
 * - 在 `FORM_QUESTION` 发（无论一次还是两次）：此刻 quest 尚无 `resourceBudget` /
 *   `stopConditions`，事件字段要么缺失、要么只能编造，直接违反 v8 §48.2「每个学习任务必须
 *   在开始前被界定」以及仓库"不得编造数据"的红线。
 * - 在 `SCOPE_AND_BUDGET` **进入**时发：同一问题——预算是该阶段**期间**才落定的，
 *   进入瞬间它还不成立。
 * - 在 `SCOPE_AND_BUDGET → PLAN_SOURCES` 发：预算刚落地、取数尚未开始，正是
 *   "开始前已被界定"。**这是定义域上唯一自洽的边。**
 *
 * 实现层面的原因：`transitionQuest` 是纯函数（返回下一个 state），"进入/退出某阶段"
 * 在代码里都只能表现为 from→to 这条边，所以发射点必须按边判定。见 `shouldRequestActiveLearning`。
 */
export const ACTIVE_LEARNING_REQUEST_EDGE = {
  from: 'SCOPE_AND_BUDGET',
  to: 'PLAN_SOURCES',
} as const satisfies { from: QuestPipelineStage, to: QuestPipelineStage }

/**
 * 请求边判定：只有 `SCOPE_AND_BUDGET → PLAN_SOURCES` 返回 true。
 * 单条边 = 单次发射，因此同一 quest 在一次流水线里不会重复发请求，也就不会撞
 * `events.idempotency_key` 的唯一约束。
 */
export function shouldRequestActiveLearning(from: QuestStage, to: QuestStage | null): boolean {
  return to !== null && from === ACTIVE_LEARNING_REQUEST_EDGE.from && to === ACTIVE_LEARNING_REQUEST_EDGE.to
}

/**
 * 完成边判定：`REFLECT` 上 `advance` 返回 `null`——`transitionQuest` 自己把这个 null 定义为
 * "没有下一阶段，即任务完成"（见该函数 doc comment）。这里复用它，而不是另造一个 `DONE`
 * 状态，好让"完成"的判据只有一处真源。
 *
 * `fail` / `abandon` **不算完成**：它们是各自独立的终端态，若也算 completed，事件名就会说谎，
 * 下游也无法再用"存在 completed"当作"学习已产出"的证据。
 */
export function shouldCompleteActiveLearning(from: QuestStage, to: QuestStage | null): boolean {
  return to === null && from === 'REFLECT'
}

/**
 * `build*Event` 的信封入参形态 = 内核唯一信封类型 {@link AijadeEventEnvelope}。
 * 以前这里手抄了一份 8 字段接口，现改为单一真源（理由同 `pef.ts` 的同名别名）。
 */
type LifecycleEnvelope = AijadeEventEnvelope

/**
 * 把一个**已界定**的 quest 包成 `aijade.active_learning.requested`（已 zod 校验）。
 *
 * 先过 `validateLearningQuest` 再构造：不满足 §48.2（无停止条件 / `spent > allocated` /
 * 缺 `experimentManifestRef`）的 quest 会**抛错**，而不是发出一条不可审计的请求。
 * 抛错而非静默返回 null，与 `schema.parse` 的行为一致，让误用声张。
 *
 * `sessionId` 显式传入而**不**用 `quest.userScope` 顶替：`LearningQuest` 契约里只有
 * `agentId` / `userScope`，没有 session 概念，两者生命周期不同，混用会让后续按 session
 * 归档的事件对不上。
 */
export function buildActiveLearningRequestedEvent(
  quest: LearningQuest,
  sessionId: string,
  envelope: LifecycleEnvelope,
) {
  const verdict = validateLearningQuest(quest)
  if (!verdict.ok)
    throw new Error(`active_learning.requested 被拒：quest 未满足 v8 §48.2 界定要求 — ${verdict.reason}`)

  return activeLearningRequestedEvent.parse({
    ...envelope,
    topic: 'aijade.active_learning.requested' as const,
    payload: {
      session_id: sessionId,
      trace_id: envelope.trace_id,
      requested_at: envelope.timestamp,
      target: quest.researchQuestion,
      quest_ref: quest.id,
      resource_budget: {
        allocated: quest.resourceBudget.allocated,
        spent: quest.resourceBudget.spent,
        unit: quest.resourceBudget.unit,
      },
      stop_conditions: [...quest.stopConditions],
    },
  })
}

/** 把走完流水线的 quest 包成 `aijade.active_learning.completed`（已 zod 校验）。 */
export function buildActiveLearningCompletedEvent(
  quest: LearningQuest,
  sessionId: string,
  envelope: LifecycleEnvelope,
  resultRef?: string,
) {
  return activeLearningCompletedEvent.parse({
    ...envelope,
    topic: 'aijade.active_learning.completed' as const,
    payload: {
      session_id: sessionId,
      trace_id: envelope.trace_id,
      completed_at: envelope.timestamp,
      quest_ref: quest.id,
      ...(resultRef === undefined ? {} : { result_ref: resultRef }),
    },
  })
}

// ---------------------------------------------------------------------------
// §48.5 — evidence confidence
// ---------------------------------------------------------------------------

export interface EvidenceQualities {
  reliability: number
  independence: number
  directness: number
  recency: number
  reproducibility: number
  /** Strength of counter-evidence (0 = none, 1 = strong). */
  counterEvidence: number
}

export const DEFAULT_CONFIDENCE_WEIGHTS = {
  reliability: 0.3,
  independence: 0.2,
  directness: 0.15,
  recency: 0.1,
  reproducibility: 0.15,
  counterEvidence: 0.2,
}

function clamp01(x: number): number {
  return Math.min(1, Math.max(0, x))
}

/**
 * §48.5 — claim confidence is NOT a vote:
 *   Conf(h) = f(Reliability, Independence, Directness, Recency, Reproducibility, CounterEvidence)
 * Counter-evidence subtracts; the result is clamped to [0,1].
 */
export function evidenceConfidence(
  q: EvidenceQualities,
  w = DEFAULT_CONFIDENCE_WEIGHTS,
): number {
  const support
    = w.reliability * clamp01(q.reliability)
      + w.independence * clamp01(q.independence)
      + w.directness * clamp01(q.directness)
      + w.recency * clamp01(q.recency)
      + w.reproducibility * clamp01(q.reproducibility)
  return clamp01(support - w.counterEvidence * clamp01(q.counterEvidence))
}

// ---------------------------------------------------------------------------
// §48.3 — source-type planning by question type
// ---------------------------------------------------------------------------

export type QuestionType = 'timely_fact' | 'academic' | 'technical' | 'everyday' | 'subjective_culture'

export interface SourcePlan {
  questionType: QuestionType
  sourceTypes: string[]
  /** Whether independent cross-validation is required before accepting. */
  crossValidate: boolean
  /** Whether multiple perspectives must be preserved (no single "truth"). */
  preservePerspectives: boolean
}

/**
 * §48.3 — plan sources by question type. Timely facts want official/primary
 * sources; academic questions want papers + reproductions; technical questions
 * want docs + code + history; everyday knowledge wants multi-source cross-check;
 * subjective/cultural content must preserve multiple perspectives.
 */
export function planSources(questionType: QuestionType): SourcePlan {
  switch (questionType) {
    case 'timely_fact':
      return { questionType, sourceTypes: ['official_announcement', 'primary_data', 'recent_reliable_report'], crossValidate: true, preservePerspectives: false }
    case 'academic':
      return { questionType, sourceTypes: ['paper', 'dataset', 'reproduction_code', 'citing_works'], crossValidate: true, preservePerspectives: false }
    case 'technical':
      return { questionType, sourceTypes: ['official_doc', 'source_code', 'issue_tracker', 'test_suite', 'version_history'], crossValidate: true, preservePerspectives: false }
    case 'everyday':
      return { questionType, sourceTypes: ['multi_source_crosscheck'], crossValidate: true, preservePerspectives: false }
    case 'subjective_culture':
      return { questionType, sourceTypes: ['multi_perspective'], crossValidate: false, preservePerspectives: true }
  }
}

// ---------------------------------------------------------------------------
// §48.4 — epistemic quarantine & shared-origin detection
// ---------------------------------------------------------------------------

/** Where a piece of content came from. */
export type ContentOrigin = 'system' | 'user' | 'web' | 'model' | 'tool'

/**
 * §48.4 / §14.4 — only content authored by the system itself may act as a system
 * instruction. Web pages, model generations and tool-extracted text are always
 * `untrusted_content` and can never become instructions.
 */
export function canBeSystemInstruction(origin: ContentOrigin): boolean {
  return origin === 'system'
}

/**
 * §48.4 — a model's own summary of a source is NOT independent evidence for that
 * source (it would be self-validation). A source is only independent evidence if
 * it is not a model-generated restatement of the claim under test.
 */
export function canBeIndependentEvidence(origin: ContentOrigin, isModelSummary: boolean): boolean {
  if (isModelSummary)
    return false
  return origin === 'web' || origin === 'tool' || origin === 'user'
}

/**
 * §48.4 — cluster sources by shared origin: two sources are the same origin if
 * they share an upstream ref OR an identical content hash. Reposts of one source
 * must not count as multi-source validation.
 */
export function sharedOriginClusters(sources: SourceRecord[]): string[][] {
  const n = sources.length
  const parent = Array.from({ length: n }, (_, i) => i)
  const find = (x: number): number => (parent[x] === x ? x : (parent[x] = find(parent[x])))
  // 既有代码的纯格式修正：单行内含 2 条语句会触 style/max-statements-per-line
  // （该错误在本次改动之前就存在，非本轮引入）。
  const union = (a: number, b: number) => {
    parent[find(a)] = find(b)
  }

  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const a = sources[i]
      const b = sources[j]
      const sameHash = a.contentHash === b.contentHash
      const sharedUpstream
        = a.upstreamRefs.some(r => b.upstreamRefs.includes(r))
          || a.upstreamRefs.includes(b.id)
          || b.upstreamRefs.includes(a.id)
      if (sameHash || sharedUpstream)
        union(i, j)
    }
  }

  const clusters = new Map<number, string[]>()
  for (let i = 0; i < n; i++) {
    const root = find(i)
    if (!clusters.has(root))
      clusters.set(root, [])
    clusters.get(root)!.push(sources[i].id)
  }
  return [...clusters.values()]
}

/** §48.4 — the number of *independent* origins (clusters), not raw sources. */
export function independentOriginCount(sources: SourceRecord[]): number {
  return sharedOriginClusters(sources).length
}
