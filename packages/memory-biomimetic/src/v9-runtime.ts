/**
 * Production-neutral v9 write runtime.
 *
 * This is the single executable path for the causal core:
 * perception evidence -> PGC state transition -> write plan -> MemoryTx ->
 * EvidenceWeave.  Storage is deliberately a port so the research kernel stays
 * independent of Drizzle, browser storage, and any particular deployment.
 */

import type {
  AijadeEvent,
  AijadeEventEnvelope,
  RiskLevel,
  VideoTranscriptObservationPayload,
  WebpageTextObservationPayload,
} from './events'
import type { MemoryPayload, MemoryTxInput, TxResult } from './memory-tx'
import type { StimulusFeature } from './pgc-state'
import type { ShadowParamsProposal } from './shadow-params'
import type {
  EvidenceChunkRow,
  EvidencePackRow,
  EvidenceWeaveRow,
  MemoryTxRow,
  MemoryVersionRow,
  PgcStateRow,
  PgcWritePlanRow,
} from './v9-schema'

import { deriveCoreStateNode } from './core-state-node'
import {
  buildLearningProposedEvidenceEvent,
  buildLearningProposedShadowParamsEvent,
} from './events'
import { MemoryTxEngine } from './memory-tx'
import { buildPgcWritePlanReadyEvent, decidePgc } from './pgc'
import { createPgcStateIntegrator, evaluateStimulus } from './pgc-state'
import {
  learningStimulusFeatures,
  shadowParamsProposalFromEvent,
  shadowProposalAsPgcCandidate,
} from './shadow-params'
import {
  buildEvidenceEventFromCandidate,
  evidenceFromSubtitleObservation,
  evidenceFromWebpageObservation,
} from './video-observation'
import { buildEvidenceWeaveCandidateReadyEvent, buildWeave, toWeaveRow } from './weave'

export interface V9PerceptionInput {
  eventId: string
  sessionId: string
  traceId: string
  correlationId: string
  timestamp: number
  originDevice: string
  privacyLevel: 0 | 1 | 2 | 3
  riskScore: number
  source: string
  content: string
  /** A feature vector is evidence, not a hidden heuristic: it is persisted in the state snapshot. */
  stimulusFeatures?: Partial<Record<StimulusFeature, number>>
  riskLevel?: RiskLevel
}

/** Minimal repository required to make the runtime durable. */
export interface V9RuntimeStore {
  readLatestPgcState: (sessionId: string) => Promise<PgcStateRow | undefined>
  persist: (artifact: V9RuntimeArtifact) => Promise<void>
}

/** All rows are exposed together so an adapter can commit them atomically. */
export interface V9RuntimeArtifact {
  evidencePack: EvidencePackRow
  evidenceChunk: EvidenceChunkRow
  pgcState: PgcStateRow
  pgcWritePlan: PgcWritePlanRow
  memoryTx: MemoryTxRow
  memoryVersions: MemoryVersionRow[]
  evidenceWeave: EvidenceWeaveRow
  events: AijadeEvent[]
}

export interface V9RuntimeResult {
  artifact: V9RuntimeArtifact
  tx: TxResult
}

/**
 * 学习事件归约入口输入。与 `V9PerceptionInput` 平行，但**必须**携带 v10 确定性/溯源字段：
 * - `tick`：确定性排序序号（来自输入学习事件，不是运行时发明）。
 * - `inputHash`：输入溯源哈希（来自输入学习事件，不是运行时发明）。
 * 这两个值会原样传播到产出的 v10 学习事件信封（v10 §0.2）。
 * `event` 是被归约的原始学习事件（aijade.learning.proposed.shadow_params 或 .evidence）。
 */
export interface V9LearningInput {
  eventId: string
  sessionId: string
  traceId: string
  correlationId: string
  timestamp: number
  originDevice: string
  privacyLevel: 0 | 1 | 2 | 3
  riskScore: number
  /** v10 确定性排序序号，由输入事件传播而来。 */
  tick: number
  /** v10 输入溯源哈希，由输入事件传播而来。 */
  inputHash: string
  /** 被归约的原始学习事件（aijade.learning.proposed.shadow_params 或 .evidence）。 */
  event: AijadeEvent
}

export interface V9LearningResult {
  artifact: V9RuntimeArtifact
  tx: TxResult
  /** 被归约出的影子参数提案（便于调用方审计/回放）。 */
  proposal: ShadowParamsProposal
}

/**
 * A 路（纯视频输入）归约入口输入。与 `V9LearningInput` 平行，但输入是**已落库的 video 观察
 * 事件**（或其 payload 经 `build*ObservationEvent` 构造的事件），输出是
 * `aijade.learning.proposed.evidence` 提案。
 *
 * `tick` / `inputHash` 是 v10 确定性/溯源字段，由**输入 video 观察事件传播而来**（服务端落库
 * 时记录），不是运行时发明；它们会原样传播到产出的 learning 事件信封。
 * `proposalId` 由调用方提供——video 观察本身不携带 proposalId，归约时才生成。
 * `event` 是被归约的 video 观察事件（topic 为
 * `aijade.video.observation.webpage_text` 或 `aijade.video.observation.video_transcript`）。
 */
export interface V9VideoObservationInput {
  eventId: string
  sessionId: string
  traceId: string
  correlationId: string
  timestamp: number
  originDevice: string
  privacyLevel: 0 | 1 | 2 | 3
  riskScore: number
  /** v10 确定性排序序号，由输入 video 观察事件传播而来。 */
  tick: number
  /** v10 输入溯源哈希，由输入 video 观察事件传播而来。 */
  inputHash: string
  /** 本次归约产出的提案 id（video 观察本身不携带 proposalId）。 */
  proposalId: string
  /** 被归约的 video 观察事件（webpage_text / video_transcript）。 */
  event: AijadeEvent
  /** 透传到产出的 learning 事件；缺省由 evidenceHash 确定性派生（见 video-observation.ts）。 */
  renderRef?: string
  appliedParamsHash?: string
  assetVersionHash?: string
}

function id(prefix: string, eventId: string): string {
  return `${prefix}_${eventId}`
}

function clampRisk(value: number): number {
  if (!Number.isFinite(value))
    return 1
  return Math.max(0, Math.min(1, value))
}

function deriveStimulus(input: V9PerceptionInput): Partial<Record<StimulusFeature, number>> {
  const lengthSignal = Math.min(1, input.content.length / 800)
  const risk = clampRisk(input.riskScore)
  return {
    stim_arousal_score: lengthSignal,
    uncertainty_load_score: risk,
    stim_drive_score: Math.max(0.15, lengthSignal * 0.5),
    stim_fatigue_score: risk * 0.2,
    ...input.stimulusFeatures,
  }
}

/**
 * 给一次归约产出的全部事件打上 `core_state_node`（v10 §4.2/§4.3）。
 *
 * 用唯一的纯函数 `deriveCoreStateNode` 按 topic + 真实控制流事实（本次 MemoryTx 是否
 * 真正落库）推导——保证与服务端回放复算同口径，从而同一 tick/inputHash 下选择一致，
 * 且回放能检出篡改。`memory_tx.committed` 事件只有 `hasMemoryVersion` 为真时才标 `S8`，
 * 否则停在 `S6`。
 */
function tagCoreStateNodes(artifact: V9RuntimeArtifact, hasMemoryVersion: boolean): void {
  artifact.events = artifact.events.map(event => ({
    ...event,
    core_state_node: deriveCoreStateNode(event.topic, { hasMemoryVersion }),
  }))
}

/**
 * Stateful PGC runtime.  One instance may serve many sessions because the
 * previous state is always read from the port before an event is processed.
 */
export class V9CausalRuntime {
  constructor(private readonly store: V9RuntimeStore) {}

  async processPerception(input: V9PerceptionInput): Promise<V9RuntimeResult> {
    if (!input.content.trim())
      throw new Error('v9 perception requires non-empty content')

    const previous = await this.store.readLatestPgcState(input.sessionId)
    const integrator = createPgcStateIntegrator(previous?.v6State)
    const stimulusFeatures = deriveStimulus(input)
    const state = integrator.step(evaluateStimulus(stimulusFeatures))

    const packId = id('ep', input.eventId)
    const chunkId = id('ec', input.eventId)
    const writeId = id('mw', input.eventId)
    const evidencePack: EvidencePackRow = {
      id: packId,
      sessionId: input.sessionId,
      source: input.source,
      createdAt: input.timestamp,
      note: `origin_device=${input.originDevice};privacy=${input.privacyLevel};risk=${clampRisk(input.riskScore)}`,
    }
    const evidenceChunk: EvidenceChunkRow = {
      id: chunkId,
      packId,
      idx: 0,
      content: input.content,
      createdAt: input.timestamp,
    }

    const decision = decidePgc({
      session_id: input.sessionId,
      trace_id: input.traceId,
      pgc_policy_version: 'pgc_policy_v1',
      candidate_memory_writes: [{
        memory_write_id: writeId,
        memory_kind: 'episodic',
        candidate_payload: { content: input.content, source: input.source },
        evidence_ids: [chunkId],
        proposed_intensity: 1,
        salience: { salience: 0.5, socialSalience: 0.2, novelty: 0.5 },
      }],
      pgc_read_context: {
        now: input.timestamp,
        last_n_events: [{ topic: 'perception_event' }],
        evidence_records: [{ id: chunkId, reliability: 1, likelihood: 1 }],
        pgc_v6_state: state,
        pgc_v6_stimulus_features: stimulusFeatures,
      },
    })

    const stateId = decision.write_plan[0]!.pgc_state_snapshot.pgc_state_id
    const pgcState: PgcStateRow = {
      id: stateId,
      sessionId: input.sessionId,
      traceId: input.traceId,
      policyVersion: 'pgc_policy_v1',
      components: decision.write_plan[0]!.pgc_state_snapshot.components,
      v6State: state,
      createdAt: input.timestamp,
    }
    const pgcWritePlan: PgcWritePlanRow = {
      id: id('pwp', input.eventId),
      pgcStateId: stateId,
      sessionId: input.sessionId,
      traceId: input.traceId,
      policyVersion: 'pgc_policy_v1',
      writePlan: decision.write_plan.map(entry => ({
        memoryWriteId: entry.memory_write_id,
        decision: entry.decision,
        finalIntensity: entry.final_intensity,
        reasonCodes: entry.reason_codes,
        expectedTests: entry.expected_tests,
        pgcStateId: entry.pgc_state_snapshot.pgc_state_id,
        // 保留完整快照（含 v6 门控诊断）：回放要复算 w_max_* 与 commit_reason，
        // 没有它就只能报 insufficient_input_snapshot —— 证据在产出点丢弃，回放永远无法成立。
        pgcStateSnapshot: entry.pgc_state_snapshot,
      })),
      contradictionReport: {
        conflictingEvidenceIds: decision.contradiction_report.conflicting_evidence_ids,
        severity: decision.contradiction_report.severity,
      },
      createdAt: input.timestamp,
    }

    const payload: MemoryPayload = {
      memory_write_id: writeId,
      normalized_payload: {
        memory_kind: 'episodic',
        content_object: { content: input.content, source: input.source },
        embedding_input_text: input.content,
        attributes: {
          tags: ['perception', input.source],
          source_claim_ids: [],
          risk_level: input.riskLevel ?? (input.riskScore >= 0.7 ? 'high' : input.riskScore >= 0.35 ? 'medium' : 'low'),
          salience: { salience: 0.5, socialSalience: 0.2, novelty: 0.5 },
        },
      },
      evidence_pack_id: packId,
      evidence_ids: [chunkId],
      provenance: { source: input.source, actor: input.originDevice },
    }
    const txInput: MemoryTxInput = {
      session_id: input.sessionId,
      trace_id: input.traceId,
      tx_id: id('tx', input.eventId),
      pgc_write_plan: decision.write_plan,
      memory_payloads: [payload],
      tx_policy: { atomicity: 'per_write', max_writes: 1 },
      // 真实的观察上下文（设备 / 隐私 / 连续风险分）在此唯一可得，故在此注入；
      // 不下沉到引擎里靠默认值，也不留给服务端落库时合成。
      envelope_context: {
        origin_device: input.originDevice,
        privacy_level: input.privacyLevel,
        risk_score: clampRisk(input.riskScore),
        evidence_refs: [packId, chunkId],
      },
    }
    const engine = new MemoryTxEngine()
    const tx = engine.commit(txInput)
    const weave = buildWeave(engine, tx.tx_id, { include_pgc_snapshot: true, include_claim_ids: true })

    const envelope: AijadeEventEnvelope = {
      event_id: id('evt', input.eventId),
      trace_id: input.traceId,
      correlation_id: input.correlationId,
      timestamp: input.timestamp,
      producer: 'v9-causal-runtime',
      origin_device: input.originDevice,
      privacy_level: input.privacyLevel,
      evidence_refs: [packId, chunkId],
      causal_context_refs: [input.traceId],
      risk_score: clampRisk(input.riskScore),
      idempotency_key: id('runtime', input.eventId),
      replay_mode: 'live' as const,
      risk_level: payload.normalized_payload.attributes.risk_level ?? 'low',
    }
    const artifact: V9RuntimeArtifact = {
      evidencePack,
      evidenceChunk,
      pgcState,
      pgcWritePlan,
      memoryTx: engine.toMemoryTxRow(txInput, tx),
      memoryVersions: engine.getVersionsForTx(tx.tx_id),
      evidenceWeave: toWeaveRow(weave, input.timestamp),
      events: [
        buildPgcWritePlanReadyEvent(decision, { ...envelope, idempotency_key: `${envelope.idempotency_key}:pgc` }),
        ...tx.events,
        buildEvidenceWeaveCandidateReadyEvent(weave, { ...envelope, idempotency_key: `${envelope.idempotency_key}:weave` }),
      ],
    }
    tagCoreStateNodes(artifact, artifact.memoryVersions.length > 0)
    await this.store.persist(artifact)
    return { artifact, tx }
  }

  /**
   * 学习事件归约 → 同一条门控链（PGC → MemoryTx → EvidenceWeave）。
   *
   * 与 `processPerception` 共用：`store.readLatestPgcState` → `createPgcStateIntegrator`
   * → `evaluateStimulus` → `decidePgc` → `MemoryTxEngine.commit` → `buildWeave` →
   * `store.persist(artifact)`。不同点：
   * 1. 输入是 v10 学习事件，先经 `shadowParamsProposalFromEvent` 归约（含 input_hash 自洽闸门）。
   * 2. 刺激特征用学习路径的 `learningStimulusFeatures`（以 confidence 为中心，不复用感知口径）。
   * 3. 产出的 v10 学习事件信封**必须**带 `tick` 与 `causality: { inputHash }`，
   *    且这两个值由 `input.tick` / `input.inputHash` 传播而来，不是运行时发明。
   */
  async processLearning(input: V9LearningInput): Promise<V9LearningResult> {
    // 归约（失败即抛 ShadowParamsIntegrityError —— input_hash 自洽闸门）。
    const proposal = shadowParamsProposalFromEvent(input.event)

    const previous = await this.store.readLatestPgcState(input.sessionId)
    const integrator = createPgcStateIntegrator(previous?.v6State)
    const stimulusFeatures = learningStimulusFeatures(proposal)
    const state = integrator.step(evaluateStimulus(stimulusFeatures))

    const packId = id('ep', input.eventId)
    const chunkId = id('ec', input.eventId)
    const writeId = id('mw', input.eventId)
    const evidencePack: EvidencePackRow = {
      id: packId,
      sessionId: input.sessionId,
      source: 'learning:shadow_params',
      createdAt: input.timestamp,
      note: `origin_device=${input.originDevice};privacy=${input.privacyLevel};risk=${clampRisk(input.riskScore)}`,
    }
    const evidenceChunk: EvidenceChunkRow = {
      id: chunkId,
      packId,
      idx: 0,
      content: JSON.stringify({ proposalId: proposal.proposalId, inputHash: proposal.inputHash, confidence: proposal.confidence }),
      createdAt: input.timestamp,
    }

    const candidate = shadowProposalAsPgcCandidate(proposal)
    const decision = decidePgc({
      session_id: input.sessionId,
      trace_id: input.traceId,
      pgc_policy_version: 'pgc_policy_v1',
      candidate_memory_writes: [candidate],
      pgc_read_context: {
        now: input.timestamp,
        last_n_events: [{ topic: input.event.topic }],
        evidence_records: [],
        pgc_v6_state: state,
        pgc_v6_stimulus_features: stimulusFeatures,
      },
    })

    const stateId = decision.write_plan[0]!.pgc_state_snapshot.pgc_state_id
    const pgcState: PgcStateRow = {
      id: stateId,
      sessionId: input.sessionId,
      traceId: input.traceId,
      policyVersion: 'pgc_policy_v1',
      components: decision.write_plan[0]!.pgc_state_snapshot.components,
      v6State: state,
      createdAt: input.timestamp,
    }
    const pgcWritePlan: PgcWritePlanRow = {
      id: id('pwp', input.eventId),
      pgcStateId: stateId,
      sessionId: input.sessionId,
      traceId: input.traceId,
      policyVersion: 'pgc_policy_v1',
      writePlan: decision.write_plan.map(entry => ({
        memoryWriteId: entry.memory_write_id,
        decision: entry.decision,
        finalIntensity: entry.final_intensity,
        reasonCodes: entry.reason_codes,
        expectedTests: entry.expected_tests,
        pgcStateId: entry.pgc_state_snapshot.pgc_state_id,
        // 保留完整快照（含 v6 门控诊断）：回放要复算 w_max_* 与 commit_reason，
        // 没有它就只能报 insufficient_input_snapshot —— 证据在产出点丢弃，回放永远无法成立。
        pgcStateSnapshot: entry.pgc_state_snapshot,
      })),
      contradictionReport: {
        conflictingEvidenceIds: decision.contradiction_report.conflicting_evidence_ids,
        severity: decision.contradiction_report.severity,
      },
      createdAt: input.timestamp,
    }

    const payload: MemoryPayload = {
      memory_write_id: writeId,
      normalized_payload: {
        memory_kind: candidate.memory_kind,
        content_object: { ...proposal },
        embedding_input_text: JSON.stringify({ proposalId: proposal.proposalId, inputHash: proposal.inputHash }),
        attributes: {
          tags: ['learning', 'shadow_params'],
          source_claim_ids: [],
          risk_level: input.riskScore >= 0.7 ? 'high' : input.riskScore >= 0.35 ? 'medium' : 'low',
          salience: candidate.salience,
        },
      },
      evidence_pack_id: packId,
      evidence_ids: [chunkId],
      provenance: { source: 'learning:shadow_params', actor: input.originDevice },
    }
    const txInput: MemoryTxInput = {
      session_id: input.sessionId,
      trace_id: input.traceId,
      tx_id: id('tx', input.eventId),
      pgc_write_plan: decision.write_plan,
      memory_payloads: [payload],
      tx_policy: { atomicity: 'per_write', max_writes: 1 },
      envelope_context: {
        origin_device: input.originDevice,
        privacy_level: input.privacyLevel,
        risk_score: clampRisk(input.riskScore),
        evidence_refs: [packId, chunkId],
        // v10：让 `memory_tx.committed`（S6/S8 的唯一记录点）也归属同一输入快照，
        // 否则按 tick 回放时看不到这次提交。值从输入事件传播，本层不发明。
        tick: input.tick,
        causality: { inputHash: input.inputHash },
      },
    }
    const engine = new MemoryTxEngine()
    const tx = engine.commit(txInput)
    const weave = buildWeave(engine, tx.tx_id, { include_pgc_snapshot: true, include_claim_ids: true })

    const envelope: AijadeEventEnvelope = {
      event_id: id('evt', input.eventId),
      trace_id: input.traceId,
      correlation_id: input.correlationId,
      timestamp: input.timestamp,
      producer: 'v9-causal-runtime',
      origin_device: input.originDevice,
      privacy_level: input.privacyLevel,
      evidence_refs: [packId, chunkId],
      causal_context_refs: [input.traceId],
      risk_score: clampRisk(input.riskScore),
      idempotency_key: id('runtime', input.eventId),
      replay_mode: 'live',
      risk_level: payload.normalized_payload.attributes.risk_level ?? 'low',
      // v10 §0.2：tick 与 causality 由输入事件传播而来，不是运行时发明。
      tick: input.tick,
      causality: { inputHash: input.inputHash },
    }

    // 产出一个 v10 学习事件（topic 跟随输入事件），信封带 tick + causality。
    const learningEvent: AijadeEvent = input.event.topic === 'aijade.learning.proposed.shadow_params'
      ? buildLearningProposedShadowParamsEvent({
          session_id: proposal.sessionId,
          proposal_id: proposal.proposalId,
          render_ref: proposal.renderRef ?? `render_${proposal.proposalId}`,
          applied_params_hash: proposal.appliedParamsHash ?? proposal.inputHash,
          asset_version_hash: proposal.assetVersionHash ?? proposal.inputHash,
          input_hash: proposal.inputHash,
          candidate_params: proposal.candidateParams,
          confidence: proposal.confidence,
        }, envelope)
      : buildLearningProposedEvidenceEvent({
          session_id: proposal.sessionId,
          proposal_id: proposal.proposalId,
          render_ref: proposal.renderRef ?? `render_${proposal.proposalId}`,
          applied_params_hash: proposal.appliedParamsHash ?? proposal.inputHash,
          asset_version_hash: proposal.assetVersionHash ?? proposal.inputHash,
          evidence_hash: proposal.evidenceHash ?? proposal.inputHash,
          claim_text: proposal.claimText ?? `shadow-params proposal ${proposal.proposalId}`,
          confidence: proposal.confidence,
        }, envelope)

    // 非 v10 前缀事件（pgc.write_plan_ready / evidence.weave_candidate_ready / memory_tx.committed）
    // 不强制携带 tick/causality，故用收窄后的信封，避免向 assertV10RequiredFields 注入多余约束。
    //
    // 但**有条件地传播** tick/causality：它们标识的是「这一次输入快照」，而不是某一个 topic。
    // 同一 tick 下由该快照派生的全部事件（学习提案、写计划、MemoryTx、织入候选）都属于
    // 同一次回放单元；若只让 v10 前缀的那一条带上，回放就一次只能验一个事件，
    // 同 tick 的其余事件反而在回放查询里**不可见**。缺失时（v9 感知路径）保持不注入。
    const baseEnvelope = {
      event_id: envelope.event_id,
      trace_id: envelope.trace_id,
      correlation_id: envelope.correlation_id,
      timestamp: envelope.timestamp,
      producer: envelope.producer,
      origin_device: envelope.origin_device,
      privacy_level: envelope.privacy_level,
      evidence_refs: envelope.evidence_refs,
      causal_context_refs: envelope.causal_context_refs,
      risk_score: envelope.risk_score,
      idempotency_key: envelope.idempotency_key,
      replay_mode: envelope.replay_mode,
      risk_level: envelope.risk_level,
      ...(envelope.tick === undefined ? {} : { tick: envelope.tick }),
      ...(envelope.causality === undefined ? {} : { causality: envelope.causality }),
    }

    const artifact: V9RuntimeArtifact = {
      evidencePack,
      evidenceChunk,
      pgcState,
      pgcWritePlan,
      memoryTx: engine.toMemoryTxRow(txInput, tx),
      memoryVersions: engine.getVersionsForTx(tx.tx_id),
      evidenceWeave: toWeaveRow(weave, input.timestamp),
      events: [
        learningEvent,
        buildPgcWritePlanReadyEvent(decision, { ...baseEnvelope, idempotency_key: `${envelope.idempotency_key}:pgc` }),
        ...tx.events,
        buildEvidenceWeaveCandidateReadyEvent(weave, { ...baseEnvelope, idempotency_key: `${envelope.idempotency_key}:weave` }),
      ],
    }
    tagCoreStateNodes(artifact, artifact.memoryVersions.length > 0)
    await this.store.persist(artifact)
    return { artifact, tx, proposal }
  }

  /**
   * A 路（纯视频输入）归约：video 观察 → 证据候选 → `aijade.learning.proposed.evidence`
   * 事件 → **同一条**门控链（PGC → MemoryTx → EvidenceWeave）。
   *
   * 这是 v10 §0.2 / §2 / §3 缺失的生产者：扩展侧已能产出 video 观察 payload 并上报服务端，
   * 但落库后没有下游把它归约成证据提案。本方法补上这一环，使 evidence 分支的「完整性锚点」
   * 闸门（`verifyShadowParamsProposalAnchor` 的 evidence 分支）首次有真实生产者喂入。
   *
   * 流程：
   * 1. 确定性归约：video 观察 payload → `EvidenceCandidate`（见 `video-observation.ts`，
   *    无网络/随机/时钟依赖）。退化输入（空 observation_text / 空 spans 等）在此抛错。
   * 2. 生成 `aijade.learning.proposed.evidence` 事件，信封带 `tick` + `causality.inputHash`，
   *    **值由输入 video 观察事件传播而来**，不是运行时发明。
   * 3. **复用 `processLearning` 走同一条门控链**：`shadowParamsProposalFromEvent`
   *    → `createPgcStateIntegrator` → `evaluateStimulus` → `decidePgc` →
   *    `MemoryTxEngine.commit` → `buildWeave` → `store.persist`。
   *
   * 产出的提案 `anchorKind === 'evidence'`、`anchorVerified === false`，并可通过
   * `verifyShadowParamsProposalAnchor`（其复算口径与本模块的 `evidenceHashFor` 逐位一致）。
   */
  async processVideoObservation(input: V9VideoObservationInput): Promise<V9LearningResult> {
    // 1. A 路归约：video 观察 → 证据候选（确定性）。
    const payload = input.event.payload as
      | WebpageTextObservationPayload
      | VideoTranscriptObservationPayload
    const candidate = input.event.topic === 'aijade.video.observation.webpage_text'
      ? evidenceFromWebpageObservation(payload as WebpageTextObservationPayload)
      : input.event.topic === 'aijade.video.observation.video_transcript'
        ? evidenceFromSubtitleObservation(payload as VideoTranscriptObservationPayload)
        : (() => {
            throw new Error(`[v9-runtime] unsupported video observation topic: ${input.event.topic}`)
          })()

    // 2. 生成证据学习事件，信封带 tick + causality（由输入事件传播而来）。
    const evidenceEvent = buildEvidenceEventFromCandidate(
      candidate,
      {
        sessionId: input.sessionId,
        proposalId: input.proposalId,
        renderRef: input.renderRef,
        appliedParamsHash: input.appliedParamsHash,
        assetVersionHash: input.assetVersionHash,
      },
      {
        event_id: id('evt', input.eventId),
        trace_id: input.traceId,
        correlation_id: input.correlationId,
        timestamp: input.timestamp,
        producer: 'v9-causal-runtime',
        origin_device: input.originDevice,
        privacy_level: input.privacyLevel,
        evidence_refs: [],
        causal_context_refs: [input.traceId],
        risk_score: clampRisk(input.riskScore),
        idempotency_key: id('runtime', input.eventId),
        replay_mode: 'live',
        risk_level: input.riskScore >= 0.7 ? 'high' : input.riskScore >= 0.35 ? 'medium' : 'low',
        // v10 §0.2：tick 与 causality 由输入事件传播而来。
        tick: input.tick,
        causality: { inputHash: input.inputHash },
      },
    )

    // 3. 复用 processLearning 的同一条门控链（不再重复实现 gating，
    //    保证与 shadow_params 分支行为一致）。
    return this.processLearning({
      eventId: input.eventId,
      sessionId: input.sessionId,
      traceId: input.traceId,
      correlationId: input.correlationId,
      timestamp: input.timestamp,
      originDevice: input.originDevice,
      privacyLevel: input.privacyLevel,
      riskScore: input.riskScore,
      tick: input.tick,
      inputHash: input.inputHash,
      event: evidenceEvent,
    })
  }
}
