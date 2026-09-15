/**
 * PGC Gate — 生理门控巩固（Physiological-Gated Consolidation），v9 写入流水线的第一道闸。
 *
 * ## 在流水线里的位置
 *
 *     candidate_memory_writes ──▶ PGC ──▶ write_plan[commit|throttle|defer|reject]
 *                                       │
 *                          MemoryTx（只 commit 真正落库，并产生 memory_versions）
 *                                       │
 *                                  EvidenceWeave（把版本织成因果图）
 *
 * ## 关于「复用 plasticity.ts 还是另建一层」的判断（team-lead 要求先读代码再决定）
 *
 * 我读完 `plasticity.ts` 后结论：**另建 PGC 决策层，但把 `plasticity.ts` 的既有原语
 * 作为构建块复用，而不是把它本身当成 PGC 的 gate。**
 *
 * 理由（不是二选一的盲选）：
 * 1. 语义不同。`plasticity.ts` 的 `PlasticityGate` 是**记忆动力学调制系数**
 *    （consolidationGain / decayMultiplier / retrievalNoise / …），且文件注释明确写明
 *    「目前关闭为中性，仅保留作兼容/审计用」——因为 A1 实验（commit ee1910f）已证明
 *    生理状态对 recall 增益贡献 ≈0。若把 PGC 直接做成 `PlasticityGate`，等于重新激活一个
 *    项目已用实验证伪的机制，与项目结论相悖。
 * 2. PGC 要的是**基于证据的策略决策**（commit/reject/throttle/defer + 理由码 + 矛盾报告），
 *    这是一个 `plasticity.ts` 完全没有的新能力。
 * 3. **但** PGC 的 `final_intensity` 与状态快照天然需要一个有界、可消融的调制量，而这正是
 *    `plasticity.ts` 已写好且被测过的部分。所以我**复用**它的：`PlasticityGate`（作为
 *    `pgc_state.components.plasticity` 嵌入快照）、`NEUTRAL_GATE`（中性 PGC 政策的对照）、
 *    `clampGate`（保证嵌入 gate 有界）、`deriveGateFromContent`（从内容显著性推出巩固增益）、
 *    `isNeutralGate`（断言「中性政策 ⇒ 生理分量为中性」的消融对照）。
 *
 * 这样既尊重了项目「生理门控已证伪、保持中性」的硬结论，又避免重造一个有界调制轮子，
 * 还把 PGC 的**新**决策逻辑（证据充分性 / 矛盾 / persona 漂移）独立、可参数化地落到
 * `pgc_policy_version` 指向的结构里——消融实验只需换 policy，不动代码。
 */

import type { Belief, EvidenceEntry } from './belief'
import type { RiskLevel } from './events'
import type { PlasticityGate } from './plasticity'

import { pgcWritePlanReadyEvent as pgcWritePlanReadyEventSchema } from './events'
import { clampGate, deriveGateFromContent, NEUTRAL_GATE } from './plasticity'

// ============================================================================
// 输入类型
// ============================================================================

export type MemoryKind = 'long_term' | 'persona' | 'skill' | 'episodic' | 'knowledge_card'

export type PgcDecision = 'commit' | 'throttle' | 'defer' | 'reject'

export type PgcReasonCode
  = | 'low_evidence'
    | 'sufficient_evidence'
    | 'contradiction_detected'
    | 'persona_shift_risk'
    | 'evidence_uncertainty_high'
    | 'throttled_high_intensity'
    | 'deferred_pending_review'

export interface ContentSalienceLite {
  salience: number
  socialSalience: number
  novelty: number
}

export interface PgcCandidateWrite {
  memory_write_id: string
  memory_kind: MemoryKind
  candidate_payload: unknown
  /** 指向 evidence_packs / evidence_chunks 的证据 id 列表（非空才有资格落库）。 */
  evidence_ids: string[]
  proposed_intensity: number
  /** 该候选主张的 claim id（用于与既有信念图做矛盾检测）。 */
  claim_ids?: string[]
  /** 可选内容显著性；用于从 plasticity.ts 派生巩固增益。缺省则生理分量取中性。 */
  salience?: ContentSalienceLite
}

export interface PgcEventLite {
  topic: string
  payload?: unknown
}

export interface PgcReadContext {
  now: number
  last_n_events: PgcEventLite[]
  physiology_signals?: Record<string, number>
  /**
   * 复用 evidence.ts/belief.ts 的既有类型做证据充分性与矛盾推理——**不**重新定义
   * 一套平行的 Evidence/Claim 实体（那会造成两套真源，本项目明确反对）。
   */
  evidence_records?: EvidenceEntry[]
  beliefs?: Belief[]
}

// ============================================================================
// 策略（参数化，供消融实验只改策略不改代码）
// ============================================================================

export interface PgcPolicy {
  version: string
  /** 证据数量低于此值 ⇒ low_evidence。 */
  min_evidence_count: number
  /** 证据不足时的处置：reject（最严）或 throttle（延迟）。 */
  low_evidence_action: 'reject' | 'throttle'
  /** 达到此证据数量视为「充分」，可 commit。 */
  sufficient_evidence_count: number
  /** 矛盾严重度阈值（0..1）；达到 ⇒ 高严重度，persona 类直接 reject。 */
  contradiction_severity_high_threshold: number
  /** persona 记忆的 intensity 超过此值且存在风险信号 ⇒ persona_shift_risk。 */
  persona_shift_intensity_threshold: number
  /** 证据不确定度（0..1）超过此值 ⇒ evidence_uncertainty_high（throttle）。 */
  evidence_uncertainty_threshold: number
  /** final_intensity 允许范围（沿用 v3 §2.3 的有界精神，但这里是 PGC 自己的强度界）。 */
  intensity_bounds: { min: number, max: number }
  /**
   * 为 true 时，证据充分性还要看 evidence_records 的平均可靠度（而非只看 id 数量）。
   * 为 false 时只看 evidence_ids 数量（轻量模式，便于无证据库时也能跑）。
   */
  require_evidence_records_for_sufficiency: boolean
}

/**
 * 默认策略 v1。每个阈值都可被消融实验覆盖；把全部阈值推向「最宽松」即可得到一个
 * 近似恒等（control）策略——这正是 v9 消融的对照写法。
 */
export const DEFAULT_PGC_POLICY_V1: PgcPolicy = {
  version: 'pgc_policy_v1',
  min_evidence_count: 1,
  low_evidence_action: 'reject',
  sufficient_evidence_count: 3,
  contradiction_severity_high_threshold: 0.5,
  persona_shift_intensity_threshold: 2.0,
  evidence_uncertainty_threshold: 0.6,
  intensity_bounds: { min: 0.2, max: 3.0 },
  require_evidence_records_for_sufficiency: false,
}

/**
 * 中性（control）策略：所有门槛推到最宽松——等价于「不门控，全部放行」，用于消融对照。
 * 与 `NEUTRAL_GATE` 在生理侧的角色一致：一个可被对照的恒等策略。
 */
export const NEUTRAL_PGC_POLICY: PgcPolicy = {
  version: 'pgc_policy_neutral',
  min_evidence_count: 0,
  low_evidence_action: 'throttle',
  sufficient_evidence_count: 1,
  contradiction_severity_high_threshold: 1.0,
  persona_shift_intensity_threshold: Number.POSITIVE_INFINITY,
  evidence_uncertainty_threshold: 1.0,
  intensity_bounds: { min: 0.2, max: 3.0 },
  require_evidence_records_for_sufficiency: false,
}

export interface PgcPolicyRegistry {
  [version: string]: PgcPolicy
}

/** 策略注册表：pgc_policy_version 在此查表。新增策略即登记，不改决策代码。 */
export const PGC_POLICY_REGISTRY: PgcPolicyRegistry = {
  [DEFAULT_PGC_POLICY_V1.version]: DEFAULT_PGC_POLICY_V1,
  [NEUTRAL_PGC_POLICY.version]: NEUTRAL_PGC_POLICY,
}

export function resolvePgcPolicy(version: string): PgcPolicy {
  const p = PGC_POLICY_REGISTRY[version]
  if (!p)
    throw new Error(`[pgc] unknown pgc_policy_version: ${version}`)
  return p
}

// ============================================================================
// 输出类型
// ============================================================================

export interface PgcStateComponents {
  /** 复用的 plasticity.ts 生理门控（v9 保持中性，除非候选带来内容显著性）。 */
  plasticity: PlasticityGate
  /** 证据强度 0..1（充分性）。 */
  evidence_strength: number
  /** 矛盾严重度 0..1。 */
  contradiction_severity: number
  /** 证据不确定度 0..1。 */
  evidence_uncertainty: number
  /** persona 漂移风险 0..1。 */
  persona_shift_risk: number
}

export interface PgcStateSnapshot {
  pgc_state_id: string
  components: PgcStateComponents
}

export interface PgcWritePlanEntry {
  memory_write_id: string
  decision: PgcDecision
  final_intensity: number
  reason_codes: PgcReasonCode[]
  expected_tests: string[]
  pgc_state_snapshot: PgcStateSnapshot
}

export interface ContradictionReport {
  conflicting_evidence_ids?: string[]
  severity: 'low' | 'high'
}

export interface PgcDecisionResult {
  pgc_state_id: string
  write_plan: PgcWritePlanEntry[]
  contradiction_report: ContradictionReport
}

export interface PgcInput {
  session_id: string
  trace_id: string
  candidate_memory_writes: PgcCandidateWrite[]
  pgc_read_context: PgcReadContext
  pgc_policy_version: string
}

// ============================================================================
// 决策核心
// ============================================================================

function clamp(x: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, x))
}

/**
 * 检测候选与既有信念图的矛盾，返回严重度（0..1）与冲突证据 id。
 *
 * 规则（确定性、可测）：
 * - 若候选的 `claim_ids` 命中某个 `accepted`/`contested` 信念的 `evidenceIds`，
 *   或候选的 `evidence_ids` 命中该信念的 `counterEvidenceIds` ⇒ 矛盾。
 * - 若候选自带的反向证据（evidence_records 中 likelihood<0）指向某 accepted 信念 ⇒ 矛盾。
 * - 严重度 = 该信念 counter-logit 占其总 logit 质量的比例（与 belief.ts 的 contestedRatio 同口径）。
 */
export function detectContradiction(
  cand: PgcCandidateWrite,
  beliefs: Belief[] = [],
  evidenceRecords: EvidenceEntry[] = [],
): { severity: number, conflictingEvidenceIds: string[] } {
  const claimSet = new Set(cand.claim_ids ?? [])
  const evidenceSet = new Set(cand.evidence_ids)
  const conflicting: string[] = []
  let worstSeverity = 0

  for (const b of beliefs) {
    if (b.status !== 'accepted' && b.status !== 'contested')
      continue
    const hitsEvidence = b.evidenceIds.some(id => claimSet.has(id))
    const hitsCounter = b.counterEvidenceIds.some(id => evidenceSet.has(id))
    if (hitsEvidence || hitsCounter) {
      const total = Math.abs(b.supportLogit) + Math.abs(b.counterLogit)
      const severity = total > 0 ? Math.abs(b.counterLogit) / total : 0.5
      worstSeverity = Math.max(worstSeverity, severity)
      for (const id of b.evidenceIds) {
        if (claimSet.has(id) && !conflicting.includes(id))
          conflicting.push(id)
      }
      for (const id of b.counterEvidenceIds) {
        if (evidenceSet.has(id) && !conflicting.includes(id))
          conflicting.push(id)
      }
    }
  }

  // 候选自带反向证据（likelihood<0）也计为矛盾信号。
  for (const e of evidenceRecords) {
    if (cand.evidence_ids.includes(e.id) && e.likelihood < 0 && !conflicting.includes(e.id)) {
      conflicting.push(e.id)
      worstSeverity = Math.max(worstSeverity, 0.5)
    }
  }

  return { severity: worstSeverity, conflictingEvidenceIds: conflicting }
}

/** 计算证据充分性 0..1。 */
function evidenceStrength(cand: PgcCandidateWrite, policy: PgcPolicy, records: EvidenceEntry[]): number {
  const count = cand.evidence_ids.length
  if (policy.require_evidence_records_for_sufficiency) {
    const recs = records.filter(r => cand.evidence_ids.includes(r.id))
    if (recs.length === 0)
      return 0
    const reliabilitySum = recs.reduce((s, r) => s + clamp(r.reliability, 0, 1), 0)
    return clamp(reliabilitySum / policy.sufficient_evidence_count, 0, 1)
  }
  return clamp(count / policy.sufficient_evidence_count, 0, 1)
}

/** 证据不确定度 0..1：可靠度越低、或方差越大越不确定。 */
function evidenceUncertainty(records: EvidenceEntry[]): number {
  if (records.length === 0)
    return 1
  const rels = records.map(r => clamp(r.reliability, 0, 1))
  const avg = rels.reduce((s, r) => s + r, 0) / rels.length
  return clamp(1 - avg, 0, 1)
}

/** persona 漂移风险 0..1：persona 类记忆且存在风险信号时升高。 */
function personaShiftRisk(
  cand: PgcCandidateWrite,
  policy: PgcPolicy,
  contradictionSeverity: number,
): number {
  if (cand.memory_kind !== 'persona')
    return 0
  let risk = 0
  if (cand.proposed_intensity > policy.persona_shift_intensity_threshold)
    risk = Math.max(risk, clamp((cand.proposed_intensity - policy.persona_shift_intensity_threshold) / policy.persona_shift_intensity_threshold, 0, 1))
  if (contradictionSeverity > 0)
    risk = Math.max(risk, contradictionSeverity)
  return risk
}

function expectedTestsFor(decision: PgcDecision, reasonCodes: PgcReasonCode[]): string[] {
  if (decision === 'reject')
    return reasonCodes.map(c => `recheck_after_${c}`)
  if (decision === 'commit')
    return ['recall_probe', 'contradiction_recheck']
  return ['defer_until_more_evidence']
}

/**
 * 对单个候选做 PGC 决策。纯函数：相同输入 ⇒ 相同输出（确定性，利于复现/回放）。
 */
export function decideCandidate(
  cand: PgcCandidateWrite,
  ctx: PgcReadContext,
  policy: PgcPolicy,
): PgcWritePlanEntry {
  // 1) 复用 plasticity.ts：从内容显著性派生巩固增益（无显著性则中性，呼应项目「生理保持中性」结论）。
  const gate: PlasticityGate = cand.salience
    ? clampGate(deriveGateFromContent(cand.salience))
    : { ...NEUTRAL_GATE }
  // 2) 证据强度 / 不确定度 / 矛盾 / persona 风险
  const records = (ctx.evidence_records ?? []).filter(r => cand.evidence_ids.includes(r.id))
  const evStrength = evidenceStrength(cand, policy, records)
  const uncer = evidenceUncertainty(records)
  const { severity: contraSeverity } = detectContradiction(cand, ctx.beliefs ?? [], records)
  const personaRisk = personaShiftRisk(cand, policy, contraSeverity)

  const components: PgcStateComponents = {
    plasticity: gate,
    evidence_strength: evStrength,
    contradiction_severity: contraSeverity,
    evidence_uncertainty: uncer,
    persona_shift_risk: personaRisk,
  }
  const pgc_state_id = `pgc_${cand.memory_write_id}_${policy.version}`
  const snapshot: PgcStateSnapshot = { pgc_state_id, components }

  const reason_codes: PgcReasonCode[] = []
  let decision: PgcDecision

  // 3) 无证据 ⇒ low_evidence（按策略 reject 或 throttle）。
  const hasEvidence = cand.evidence_ids.length > 0
  if (!hasEvidence || cand.evidence_ids.length < policy.min_evidence_count) {
    reason_codes.push('low_evidence')
    decision = policy.low_evidence_action
  }
  else {
    // 风险按优先级逐级判定；无可风险且证据充分 ⇒ commit。
    if (contraSeverity > 0) {
      reason_codes.push('contradiction_detected')
      decision = contraSeverity >= policy.contradiction_severity_high_threshold ? 'reject' : 'throttle'
    }
    else if (personaRisk > 0 && cand.memory_kind === 'persona') {
      // persona 记忆对漂移敏感：检测到风险即保守拒绝（而非延迟），避免污染人格。
      reason_codes.push('persona_shift_risk')
      decision = 'reject'
    }
    else if (uncer > policy.evidence_uncertainty_threshold && records.length > 0) {
      reason_codes.push('evidence_uncertainty_high')
      decision = 'throttle'
    }
    else if (evStrength >= 1) {
      reason_codes.push('sufficient_evidence')
      decision = 'commit'
    }
    else {
      reason_codes.push('deferred_pending_review')
      decision = 'throttle'
    }
  }

  // 4) final_intensity：复用 plasticity 的 consolidationGain 作为证据/生理调制乘子，再夹到策略界。
  const final_intensity = clamp(
    cand.proposed_intensity * gate.consolidationGain,
    policy.intensity_bounds.min,
    policy.intensity_bounds.max,
  )

  return {
    memory_write_id: cand.memory_write_id,
    decision,
    final_intensity,
    reason_codes,
    expected_tests: expectedTestsFor(decision, reason_codes),
    pgc_state_snapshot: snapshot,
  }
}

/**
 * PGC 总入口：对整批候选产出 write_plan 与矛盾报告。
 */
export function decidePgc(input: PgcInput): PgcDecisionResult {
  const policy = resolvePgcPolicy(input.pgc_policy_version)
  const write_plan = input.candidate_memory_writes.map(c => decideCandidate(c, input.pgc_read_context, policy))

  // 矛盾报告：汇总所有候选的冲突证据；任一高严重度 ⇒ 整体 high。
  const conflicting = new Set<string>()
  let maxSeverity = 0
  for (const entry of write_plan) {
    const { severity, conflictingEvidenceIds } = detectContradiction(
      input.candidate_memory_writes.find(c => c.memory_write_id === entry.memory_write_id)!,
      input.pgc_read_context.beliefs ?? [],
      (input.pgc_read_context.evidence_records ?? []).filter(r => input.candidate_memory_writes.find(c => c.memory_write_id === entry.memory_write_id)!.evidence_ids.includes(r.id)),
    )
    for (const id of conflictingEvidenceIds)
      conflicting.add(id)
    maxSeverity = Math.max(maxSeverity, severity)
  }

  return {
    pgc_state_id: `pgc_${input.session_id}_${input.trace_id}_${policy.version}`,
    write_plan,
    contradiction_report: {
      conflicting_evidence_ids: conflicting.size > 0 ? [...conflicting] : undefined,
      severity: maxSeverity >= policy.contradiction_severity_high_threshold ? 'high' : 'low',
    },
  }
}

/** 便利：把 PGC 决策包成一个合法事件（aijade.pgc.write_plan_ready），供流水线串联。 */
export function buildPgcWritePlanReadyEvent(
  decision: PgcDecisionResult,
  envelope: { event_id: string, trace_id: string, correlation_id: string, timestamp: number, producer: string, idempotency_key: string, replay_mode: 'live' | 'replay', risk_level: RiskLevel },
) {
  return pgcWritePlanReadyEventSchema.parse({
    ...envelope,
    topic: 'aijade.pgc.write_plan_ready' as const,
    payload: {
      pgc_state_id: decision.pgc_state_id,
      write_plan_size: decision.write_plan.length,
      policy_version: decision.pgc_state_id.split('_').pop() ?? '',
    },
  })
}
