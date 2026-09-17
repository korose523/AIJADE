/**
 * 学习影子参数（Shadow Params）—— v10 学习事件 → 证据态 + 影子参数候选 的归约层。
 *
 * ───────────────────────────────────────────────────────────────────────────
 * ⚠️ 与 `identity.ts` 的 CDI 身份影子评测**不是一回事**：
 *
 * - `identity.ts` 的 `evaluateShadow` / `solveIdentityUpdate`（v7 §11.2 / §11.3）是
 *   **身份连续性**模型：它在一组受约束的可发展身份参数（constitutional / character /
 *   expressive）上做小步约束求解、漂移报告与签名版本。它评测的是"我是谁"的演化，且
 *   明文禁止驱动记忆耐久/显著性（H2c 护栏）。
 * - 本文件的 `ShadowParamsProposal` 是**学习系统内部**的影子参数候选：把
 *   `aijade.learning.proposed.shadow_params`（含 candidate_params）与
 *   `aijade.learning.proposed.evidence`（含 evidence_hash / claim_text）两类 v10 事件
 *   **归约为**一个可经既有 EvidenceGate 与 PGC 门控裁决的候选写入。它评测的是"这次
 *   学习提出的参数改动是否值得固化"，走的是 `decidePgc` 的 commit/reject 判定链，
 *   与身份层完全正交——请勿把两者的 `shadow` 概念混为一谈。
 * ───────────────────────────────────────────────────────────────────────────
 *
 * 全部为纯函数（除读取事件 payload 外无副作用），确定性：同输入 ⇒ 逐位同输出。
 * 无任何随机数 / 墙上时钟依赖。
 */

import type {
  AijadeEvent,
  LearningProposedEvidencePayload,
  LearningProposedShadowParamsPayload,
} from './events'
import type { MemoryKind, PgcCandidateWrite } from './pgc'
import type { StimulusFeature } from './pgc-state'

import { contentHash } from './v9-hash'

// ============================================================================
// 领域类型
// ============================================================================

/**
 * 提案完整性锚点**类型**：决定 `inputHash` 该用哪一组字段复算。
 *
 * 为什么需要这个显式判别（而不是靠 `candidateParams` 是否为空来猜）：`shadow_params`
 * 提案的 `candidate_params` 合法地可以是空对象，用"空即 evidence"来判会**误判分支**，
 * 而误判分支的后果是锚点复算用了错的字段集 —— 一个恒不通过的闸门与一个恒通过的闸门
 * 一样无用。所以分支由归约时显式记录，不由下游推断。
 */
export type ShadowParamsAnchorKind
  /** 来自 `shadow_params`：锚点是 `candidate_params`。 */
  = | 'shadow_params'
  /** 来自 `evidence`：锚点是证据主体 `{ evidence_hash, claim_text }`。 */
    | 'evidence'

/** 一个被归约出的学习影子参数提案。 */
export interface ShadowParamsProposal {
  /** 提案 id（来自事件 payload.proposal_id）。 */
  proposalId: string
  /** 会话 id。 */
  sessionId: string
  /**
   * 输入哈希。是对提案主体（`candidate_params` 或证据主体）的规范化哈希快照。
   *
   * ⚠️ 这个值的**来源不是一个**，`anchorVerified` 就是用来区分这两种情况的 ——
   * 不要把它一律当成"已验证过"。
   */
  inputHash: string
  /** 锚点类型：决定复算 `inputHash` 时用哪一组字段（见 {@link ShadowParamsAnchorKind}）。 */
  anchorKind: ShadowParamsAnchorKind
  /**
   * `inputHash` 是否**与生产方声明的值比对过**。
   *
   * - `shadow_params` 分支：payload 里有 `input_hash`，归约时复算并比对 ⇒ `true`；
   *   不一致直接抛 `ShadowParamsIntegrityError`。
   * - `evidence` 分支：v10 契约里**没有** `input_hash` 字段，没有声明值可比 ⇒ `false`。
   *   该分支的 `inputHash` 是由证据主体**推导**出来的，不是校验出来的。
   *
   * `false` 不等于"值不可信"：它表示"这一支没有可比的声明值"。真正需要的是**可复算**——
   * 任何持有 proposal 的一方都能用 {@link verifyShadowParamsProposalAnchor} 从提案自身的
   * 字段重算并比对，这是 promotion 侧必须做的一步（见 `v9-promotion.ts`）。
   */
  anchorVerified: boolean
  /** 候选参数（来自 shadow_params 事件的 candidate_params）。evidence 事件归约时为空对象。 */
  candidateParams: Record<string, unknown>
  /** 置信度 0..1（来自事件 confidence）。 */
  confidence: number
  /** 渲染轨迹引用（可选，透传自事件）。 */
  renderRef?: string
  /** 实写通道指纹（可选，透传自事件）。 */
  appliedParamsHash?: string
  /** 模型资产版本哈希（可选，透传自事件）。 */
  assetVersionHash?: string
  /** 证据哈希（仅 evidence 事件归约时存在）。 */
  evidenceHash?: string
  /** 声明文本（仅 evidence 事件归约时存在）。 */
  claimText?: string
}

// ============================================================================
// 失败路径（统一为可辨识的 Error）
// ============================================================================

/**
 * 归约过程中可辨识的失败：目前唯一来源是 `input_hash` 自洽校验不通过。
 * 全模块统一用这个 Error 类表达"闸门拒绝"，调用方可按 `name`/`instanceof` 识别。
 */
export class ShadowParamsIntegrityError extends Error {
  constructor(message: string) {
    super(`[shadow-params] ${message}`)
    this.name = 'ShadowParamsIntegrityError'
  }
}

// ============================================================================
// input_hash 重算口径（统一、可复现）
// ============================================================================

/**
 * 计算（并校验）学习提案的 `input_hash`，口径全局唯一：
 *
 *     input_hash = contentHash({ session_id, proposal_id, body })
 *
 * 其中 `body` 是提案主体——`shadow_params` 事件为 `candidate_params`；`evidence` 事件为
 * `{ evidence_hash, claim_text }`。把 `proposal_id` 作为上下文锚点，使同一组主体在不同
 * 提案下得到不同的 `input_hash`，避免跨提案碰撞。`contentHash` 是规范化 JSON → sha256，
 * 确定性、逐位可复现。生产者必须用**同一口径**生成 `input_hash`，内核才能校验自洽。
 *
 * 这是 v10 "统一失败路径" 的真实闸门——比对不一致即抛 `ShadowParamsIntegrityError`，
 * 绝不允许退化成恒真式。
 */
export function computeLearningInputHash(sessionId: string, proposalId: string, body: unknown): string {
  return contentHash({ session_id: sessionId, proposal_id: proposalId, body })
}

/**
 * 从提案**自身的字段**复算 `inputHash` 并比对，返回可判别的结果。
 *
 * 为什么需要它（而不是只在归约时校验一次）：提案会以 JSON 形式跨进程流转 ——
 * promotion worker 就是从 Redis 队列里把 proposal **反序列化**出来直接用的。
 * 只信任反序列化结果，等于"队列里放什么就晋升什么"，`input_hash` 这道闸门在
 * 归约之后不再起任何作用。本函数把闸门变成**任何持有提案的一方都能重放的动作**。
 *
 * 两个分支都必须通过：
 * - `shadow_params`：用 `candidateParams` 复算；
 * - `evidence`：用 `{ evidence_hash, claim_text }` 复算；缺任一字段即**拒绝**
 *   （拒绝而不是跳过 —— "算不出来"绝不能被当成"算出来且一致"）。
 *
 * 确定性：`contentHash` 用规范化 JSON（键按字典序），因此 JSON 往返不改变结果。
 */
export function verifyShadowParamsProposalAnchor(
  proposal: ShadowParamsProposal,
): { ok: true } | { ok: false, reason: string } {
  if (proposal.anchorKind === 'shadow_params') {
    const expected = computeLearningInputHash(proposal.sessionId, proposal.proposalId, proposal.candidateParams)
    if (expected !== proposal.inputHash) {
      return {
        ok: false,
        reason: `shadow_params input_hash mismatch: declared=${proposal.inputHash} recomputed=${expected}`,
      }
    }
    return { ok: true }
  }

  if (proposal.evidenceHash === undefined || proposal.claimText === undefined) {
    return {
      ok: false,
      reason: 'evidence proposal is missing evidence_hash / claim_text, so its anchor cannot be recomputed',
    }
  }
  const expected = computeLearningInputHash(proposal.sessionId, proposal.proposalId, {
    evidence_hash: proposal.evidenceHash,
    claim_text: proposal.claimText,
  })
  if (expected !== proposal.inputHash) {
    return {
      ok: false,
      reason: `evidence input_hash mismatch: declared=${proposal.inputHash} recomputed=${expected}`,
    }
  }
  return { ok: true }
}

// ============================================================================
// 归约：两类学习事件 → ShadowParamsProposal
// ============================================================================

/**
 * 从 `aijade.learning.proposed.shadow_params` 或 `aijade.learning.proposed.evidence`
 * 事件归约出 `ShadowParamsProposal`。
 *
 * 归约时会**强制 `input_hash` 自洽**：用 `computeLearningInputHash` 对提案主体重算，
 * 与 payload 声明的 `input_hash` 比对；不一致立即抛 `ShadowParamsIntegrityError`（闸门拒绝）。
 *
 * 确定性：相同输入 ⇒ 完全相同的返回值（无任何随机/时钟依赖）。
 */
export function shadowParamsProposalFromEvent(event: AijadeEvent): ShadowParamsProposal {
  if (event.topic === 'aijade.learning.proposed.shadow_params') {
    const p = event.payload as LearningProposedShadowParamsPayload
    const recomputed = computeLearningInputHash(p.session_id, p.proposal_id, p.candidate_params)
    if (recomputed !== p.input_hash) {
      throw new ShadowParamsIntegrityError(
        `shadow_params input_hash mismatch: declared=${p.input_hash} recomputed=${recomputed}`,
      )
    }
    return {
      proposalId: p.proposal_id,
      sessionId: p.session_id,
      inputHash: p.input_hash,
      // 本分支**有**声明值可比（payload.input_hash），且上面刚比对通过，故 anchorVerified=true。
      // 这不代表下游可以跳过复算：proposal 会序列化后跨进程流转，反序列化方仍须
      // 自行调 `verifyShadowParamsProposalAnchor`（见 `v9-promotion.ts`）。
      anchorKind: 'shadow_params',
      anchorVerified: true,
      candidateParams: p.candidate_params,
      confidence: p.confidence,
      renderRef: p.render_ref,
      appliedParamsHash: p.applied_params_hash,
      assetVersionHash: p.asset_version_hash,
    }
  }

  if (event.topic === 'aijade.learning.proposed.evidence') {
    const p = event.payload as LearningProposedEvidencePayload
    // evidence 事件 schema（v10 契约）不含 input_hash 字段，没有外部声明值可供比对，
    // 故本分支**不跑** input_hash 闸门；改为以证据主体自算哈希作为提案的 inputHash
    // （确定性、可复现，与 shadow_params 分支用同一 `computeLearningInputHash` 口径）。
    // ⚠️ 正因为这里没有可比的声明值，这个 hash 在归约时是**恒自洽**的 —— 它不构成闸门。
    // 真正的校验发生在持有提案、准备据此行动的一侧（见 `verifyShadowParamsProposalAnchor`，
    // 以及 `apps/server/src/services/domain/v9-promotion.ts` 的 promotion 前置检查）。
    const computed = computeLearningInputHash(p.session_id, p.proposal_id, {
      evidence_hash: p.evidence_hash,
      claim_text: p.claim_text,
    })
    return {
      proposalId: p.proposal_id,
      sessionId: p.session_id,
      inputHash: computed,
      // 本分支**没有**声明值可比（契约无 input_hash 字段），故 anchorVerified=false：
      // 这个 inputHash 是推导出来的，不是校验出来的。它仍然**可复算** ——
      // 下游（promotion）必须调 `verifyShadowParamsProposalAnchor` 自行核对，
      // 不能因为这里已经算过一次就当它天然可信。
      anchorKind: 'evidence',
      anchorVerified: false,
      candidateParams: {},
      confidence: p.confidence,
      renderRef: p.render_ref,
      appliedParamsHash: p.applied_params_hash,
      assetVersionHash: p.asset_version_hash,
      evidenceHash: p.evidence_hash,
      claimText: p.claim_text,
    }
  }

  throw new ShadowParamsIntegrityError(
    `unsupported event topic for shadow-params reduction: ${event.topic}`,
  )
}

// ============================================================================
// 映射：ShadowParamsProposal → 既有 PgcCandidateWrite（只读复用 pgc.ts）
// ============================================================================

export interface ShadowProposalToCandidateOpts {
  /** 目标 memory_kind（默认 knowledge_card）。不改 pgc.ts，仅在外部构造既有形状。 */
  memoryKind?: MemoryKind
  /** 覆盖 evidence_ids；默认由 proposalId 确定性派生（非空，满足 PGC 证据链要求）。 */
  evidenceIds?: string[]
  /** 覆盖 memory_write_id；默认由 proposalId 确定性派生。 */
  memoryWriteId?: string
}

/**
 * 把归约出的提案映射成既有 `PgcCandidateWrite`，以便直接喂给 `decidePgc`。
 *
 * 映射口径（注释说明，全模块一致）：
 * - `candidate_payload`：放提案本体（含 input_hash / confidence / candidateParams），
 *   供审计回放还原。
 * - `evidence_ids`：非空；默认 `['shadow_<proposalId>']`，因为学习候选的"证据"就是这条
 *   影子参数提案本身（其 input_hash 即证据溯源锚点）。可由 opts 覆盖。
 * - `salience` 由 `confidence` 派生：
 *     salience       = confidence    （高置信 → 高显著性）
 *     socialSalience = 0             （学习影子参数非社交信号）
 *     novelty        = 1 - confidence（低置信 → 越新颖/越未确定，需更多证据）
 * - `proposed_intensity`：直接取 `confidence`（夹到 [0,1]），作为 PGC 强度初值。
 * - `memory_kind`：默认 `knowledge_card`（→ τ=semantic），可由 opts 覆盖。
 */
export function shadowProposalAsPgcCandidate(
  proposal: ShadowParamsProposal,
  opts: ShadowProposalToCandidateOpts = {},
): PgcCandidateWrite {
  const memoryKind = opts.memoryKind ?? 'knowledge_card'
  const evidenceIds = opts.evidenceIds ?? [`shadow_${proposal.proposalId}`]
  const memoryWriteId = opts.memoryWriteId ?? `sp_${proposal.proposalId}`
  const confidence = Math.max(0, Math.min(1, proposal.confidence))
  return {
    memory_write_id: memoryWriteId,
    memory_kind: memoryKind,
    candidate_payload: { ...proposal },
    evidence_ids: evidenceIds,
    proposed_intensity: confidence,
    salience: {
      salience: confidence,
      socialSalience: 0,
      novelty: 1 - confidence,
    },
  }
}

// ============================================================================
// 学习信号 → 刺激特征（与 v9-runtime.deriveStimulus 感知路径口径无关）
// ============================================================================

/**
 * 把学习提案映射为四维状态积分器所需的刺激特征。
 *
 * ⚠️ 本函数**刻意不复用** `v9-runtime.ts` 里 `deriveStimulus` 那套"按内容长度"派生
 * 刺激特征的逻辑——那是感知路径的口径，与学习路径无关。学习路径以 `confidence` 为中心：
 * - `uncertainty_load_score` = 1 - confidence （置信越低，不确定性负载越高）
 * - `stim_arousal_score`     = confidence     （高置信学习信号更"激活"）
 * - `stim_drive_score`       = confidence     （高置信 → 更强的巩固驱动）
 * - `stim_fatigue_score`     = 0             （学习信号本身不增加疲劳）
 *
 * 确定性：纯函数，同输入 ⇒ 同输出。
 */
export function learningStimulusFeatures(
  proposal: ShadowParamsProposal,
): Partial<Record<StimulusFeature, number>> {
  const c = Math.max(0, Math.min(1, proposal.confidence))
  return {
    uncertainty_load_score: 1 - c,
    stim_arousal_score: c,
    stim_drive_score: c,
    stim_fatigue_score: 0,
  }
}
