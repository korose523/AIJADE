/**
 * A 路（纯视频输入）归约：把两类 video 观察事件**确定性地**归约为「证据候选」。
 *
 * 这是 v10 §0.2 / §2 / §3 规定的 A 路学习归约：纯视频输入 → EvidencePack + 约束性
 * 意图条件；产出 `aijade.learning.proposed.evidence`。本模块是这条链在**内核侧**缺失的
 * 生产者：扩展侧（`plugins/aijade-plugin-web-extension`）已能产出 video 观察 payload 并
 * 经 REST 上报服务端，但服务端落库后**没有下游**把它归约成证据提案，导致
 * `aijade.learning.proposed.evidence` 这个 topic 端到端从未被真实数据走过、其「完整性
 * 锚点」闸门（`verifyShadowParamsProposalAnchor` 的 evidence 分支）也从未被真实生产者喂过。
 *
 * 本模块填补这一环：输入是观察 payload，输出是「证据候选」——
 * `{ sourceKind, sourceRef, claimText, evidenceHash, confidence }`，**不是** LLM 摘要。
 * 全程纯函数：无网络调用、无随机数、无墙上时钟、无对 Map/Set 迭代顺序的隐式依赖。
 *
 * ⚠️ 与下游 promotion 的耦合（务必保持逐位一致，见 `evidenceHashFor` 注释）：
 * promotion 用 `computeLearningInputHash(sessionId, proposalId, { evidence_hash, claim_text })`
 * 复算提案 `input_hash`。本模块产出的 `evidenceHash` / `claimText` 必须**原样**作为
 * `evidence_hash` / `claim_text` 传入事件（不做任何规范化/再拼接），否则闸门会恒拒。
 */

import type {
  AijadeEvent,
  AijadeEventEnvelope,
  LearningProposedEvidencePayload,
  VideoTranscriptObservationPayload,
  WebpageTextObservationPayload,
} from './events'

import { buildLearningProposedEvidenceEvent } from './events'
import { computeLearningInputHash } from './shadow-params'
import { contentHash } from './v9-hash'

/** 视频观察的来源类型（用于证据哈希的 `source_kind` 维度）。 */
export type VideoObservationKind
  = | 'webpage_text'
    | 'video_transcript'

/**
 * 一次归约产出的「证据候选」—— 还未经 PGC 门控裁决（那是 `processVideoObservation`
 * 的职责），只是从观察 payload 中抽出的确定性证据主体。
 */
export interface EvidenceCandidate {
  /** 来源类型：网页文本 / 字幕。 */
  sourceKind: VideoObservationKind
  /** 来源锚：网页用 `content_hash`，字幕用 `transcript_hash`（均为观察 payload 自带且非空）。 */
  sourceRef: string
  /** 证据声明文本：网页用 `observation_text`，字幕用 `caption_text`（原样，不规范化）。 */
  claimText: string
  /**
   * 证据哈希（确定性）。计算口径见 {@link evidenceHashFor}。
   * ⚠️ 这个字符串会被原样作为 `evidence_hash` 写入事件，并参与下游 `input_hash` 复算，
   * 本模块绝不对其再做规范化。
   */
  evidenceHash: string
  /** 确定性置信度 0..1（由观察的跨度数量推导，见两个 `evidenceFrom*` 函数）。 */
  confidence: number
}

export interface EvidenceCandidateToEventPayloadOpts {
  sessionId: string
  /** 本次归约产出的提案 id（video 观察本身不携带 proposalId，由调用方提供）。 */
  proposalId: string
  /**
   * 以下三项对应 `learningProposedEvidenceSchema` 的必填字段（`.min(1)`）。
   * 省略时由 `evidenceHash` 确定性派生（非空、可复现），保证事件可被 zod 接受。
   */
  renderRef?: string
  appliedParamsHash?: string
  assetVersionHash?: string
  /** 覆盖置信度；缺省用 candidate.confidence。 */
  confidence?: number
}

function clamp01(value: number): number {
  if (!Number.isFinite(value))
    return 0
  return Math.max(0, Math.min(1, value))
}

/**
 * 计算证据哈希（确定性、逐位可复现）—— A 路归约的哈希口径**唯一真源**。
 *
 *     evidenceHash = contentHash({ source_kind, source_ref, claim_text })
 *
 * `contentHash` 是规范化 JSON → sha256（`v9-hash.ts`），键按字典序、数组保序，因此
 * 同一份 `(sourceKind, sourceRef, claimText)` 永远得到同一哈希。
 *
 * ## ⚠️ 与 `verifyShadowParamsProposalAnchor` 的口径耦合（核心不变量）
 *
 * 下游 promotion 复算 `input_hash` 时用的是
 * `computeLearningInputHash(sessionId, proposalId, { evidence_hash, claim_text })`，
 * 其中 `evidence_hash` 取自事件 payload 的 `evidence_hash`、`claim_text` 取自 `claim_text`。
 * 本模块通过 {@link evidenceCandidateToEventPayload} 把 `candidate.evidenceHash` →
 * `evidence_hash`、`candidate.claimText` → `claim_text` **原样**写入，不做任何规范化，
 * 因此 promotion 复算出的 `input_hash` 与 `shadowParamsProposalFromEvent` 从同一份
 * `evidence_hash`/`claim_text` 复算出的 `input_hash` **逐位一致** → 闸门闭合。
 * 任何在这里对 `evidenceHash`/`claimText` 做再拼接或规范化的动作都会破坏该不变量。
 */
export function evidenceHashFor(
  sourceKind: VideoObservationKind,
  sourceRef: string,
  claimText: string,
): string {
  return contentHash({ source_kind: sourceKind, source_ref: sourceRef, claim_text: claimText })
}

/**
 * 网页文本观察 → 证据候选（A 路 / webpage_text）。
 *
 * 来源锚取 `content_hash`（payload 自带、zod 已保证非空）；声明文本取
 * `observation_text`（原样，不截断、不摘要）。退化输入（空文本 / 空 content_hash /
 * 空 spans）直接抛错——**拒绝**而不是产出「看似成功但内容为空」的提案。
 */
export function evidenceFromWebpageObservation(
  payload: WebpageTextObservationPayload,
): EvidenceCandidate {
  if (!payload.observation_text || payload.observation_text.trim() === '')
    throw new Error('[video-observation] webpage observation requires non-empty observation_text')
  if (!payload.content_hash || payload.content_hash.trim() === '')
    throw new Error('[video-observation] webpage observation requires non-empty content_hash')
  if (!Array.isArray(payload.spans) || payload.spans.length === 0)
    throw new Error('[video-observation] webpage observation requires at least one span')

  const sourceRef = payload.content_hash
  const claimText = payload.observation_text
  const evidenceHash = evidenceHashFor('webpage_text', sourceRef, claimText)
  // 确定性置信度：跨度数越多，证据越扎实（封顶 1.0）。
  const confidence = clamp01(0.5 + 0.1 * Math.min(payload.spans.length, 5))
  return { sourceKind: 'webpage_text', sourceRef, claimText, evidenceHash, confidence }
}

/**
 * 字幕观察 → 证据候选（A 路 / video_transcript）。
 *
 * 来源锚取 `transcript_hash`；声明文本取 `caption_text`（原样）。退化输入同样**拒绝**。
 */
export function evidenceFromSubtitleObservation(
  payload: VideoTranscriptObservationPayload,
): EvidenceCandidate {
  if (!payload.caption_text || payload.caption_text.trim() === '')
    throw new Error('[video-observation] subtitle observation requires non-empty caption_text')
  if (!payload.transcript_hash || payload.transcript_hash.trim() === '')
    throw new Error('[video-observation] subtitle observation requires non-empty transcript_hash')
  if (!Array.isArray(payload.time_spans) || payload.time_spans.length === 0)
    throw new Error('[video-observation] subtitle observation requires at least one time_span')

  const sourceRef = payload.transcript_hash
  const claimText = payload.caption_text
  const evidenceHash = evidenceHashFor('video_transcript', sourceRef, claimText)
  const confidence = clamp01(0.5 + 0.1 * Math.min(payload.time_spans.length, 5))
  return { sourceKind: 'video_transcript', sourceRef, claimText, evidenceHash, confidence }
}

/**
 * 把证据候选映射为 `learningProposedEvidenceSchema` 的 payload。
 *
 * **自洽性约定（与下游 promotion 同口径）**：`evidence_hash` / `claim_text` 原样取自
 * `candidate.evidenceHash` / `candidate.claimText`，不做任何规范化。这样就保证了
 * `computeLearningInputHash(sessionId, proposalId, { evidence_hash, claim_text })` 与
 * `shadowParamsProposalFromEvent` 复算的 `input_hash` 逐位一致，闸门闭合。
 *
 * 注意：`learningProposedEvidenceSchema` **不含** `input_hash` 字段（v10 契约如此），
 * 故此处只生成 payload，不携带 input_hash——它会在 `shadowParamsProposalFromEvent` 归约时
 * 由证据主体推导出来。
 */
export function evidenceCandidateToEventPayload(
  candidate: EvidenceCandidate,
  opts: EvidenceCandidateToEventPayloadOpts,
): LearningProposedEvidencePayload {
  // 缺省值的确定性派生：由 evidenceHash 做两次不同的内容哈希，保证非空且可复现。
  const renderRef = opts.renderRef ?? `render_${opts.proposalId}`
  const appliedParamsHash = opts.appliedParamsHash ?? contentHash({ t: 'applied', e: candidate.evidenceHash })
  const assetVersionHash = opts.assetVersionHash ?? contentHash({ t: 'asset', e: candidate.evidenceHash })
  const confidence = opts.confidence ?? candidate.confidence
  return {
    session_id: opts.sessionId,
    proposal_id: opts.proposalId,
    render_ref: renderRef,
    applied_params_hash: appliedParamsHash,
    asset_version_hash: assetVersionHash,
    evidence_hash: candidate.evidenceHash,
    claim_text: candidate.claimText,
    confidence: clamp01(confidence),
  }
}

/**
 * 便捷构造 `aijade.learning.proposed.evidence` 事件，信封带 `tick` + `causality`
 * （由 video 观察事件传播而来，不是运行时发明）。供 `processVideoObservation` 与测试使用。
 */
export function buildEvidenceEventFromCandidate(
  candidate: EvidenceCandidate,
  opts: EvidenceCandidateToEventPayloadOpts,
  envelope: AijadeEventEnvelope,
): AijadeEvent {
  const payload = evidenceCandidateToEventPayload(candidate, opts)
  return buildLearningProposedEvidenceEvent(payload, envelope)
}

/**
 * 自检辅助：用与下游 promotion **完全相同**的口径复算提案 `input_hash`。
 *
 * 返回 `computeLearningInputHash(sessionId, proposalId, { evidence_hash, claim_text })`，
 * 其中 `evidence_hash`/`claim_text` 取自 candidate 的原样字段。测试可据此断言本模块与
 * `shadowParamsProposalFromEvent` 的产出逐位一致（见 video-observation.test.ts 的锚点闭合用例）。
 */
export function evidenceProposalInputHash(
  sessionId: string,
  proposalId: string,
  candidate: EvidenceCandidate,
): string {
  return computeLearningInputHash(sessionId, proposalId, {
    evidence_hash: candidate.evidenceHash,
    claim_text: candidate.claimText,
  })
}
