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
import type { PgcState4, StimulusFeature, Tau } from './pgc-state'
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
  /**
   * v6 四维内生状态 s_t = [a, c, d, f]（可选）。**提供后走 v6 门控**；不提供则保持
   * 既有纯证据阈值策略不变（向后兼容，478 个既有测试不受影响）。v6 是叠加层，不是替换。
   */
  pgc_v6_state?: PgcState4
  /**
   * v6 刺激特征（可选，随状态一起提供，仅用于审计/可解释性；门控本身只消费 s_t）。
   */
  pgc_v6_stimulus_features?: Partial<Record<StimulusFeature, number>>
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
// v6 四维内生状态 → 写入门控（第 4 份规范参数）
// ============================================================================
//
// 这些机制此前只停留在文档规范，未在代码实现。本段首次把 v6 的 τ 映射、参数基线与
// 门控决策顺序落成真实代码。参数取"第 4 份规范"：第 1 份四种 τ 的 w 上限全部低于
// commit 阈值（构造性零，永远无法 commit），第 4 份四种 τ 的 w 上限均为 1.0，可 commit。

/** memory_kind（5 个，代码真源）→ τ（4 种）。注意 `skill` 在作者的映射表里被漏掉，这里显式覆盖。 */
export const TAU_BY_MEMORY_KIND: Record<MemoryKind, Tau> = {
  episodic: 'episodic',
  persona: 'affective',
  skill: 'procedural',
  long_term: 'semantic',
  knowledge_card: 'semantic',
}

/**
 * 论文/展示层的 4 类标签（τ 的文本别名）。
 *
 * ⚠️ 这是 τ → 标签的**重命名**，不是第二套分类：4 个标签与 4 个 τ 一一对应。
 * 因此必须由 `TAU_BY_MEMORY_KIND` 派生（见 `displayLabelForMemoryKind`），
 * 不得手写「MemoryKind → 标签」的第二张表，否则 `long_term` 与 `knowledge_card`
 * 压缩到同一类这条关系会在两处漂移。
 */
export type TauDisplayLabel = 'episode' | 'emotion' | 'skill' | 'knowledge'

/** τ → 展示标签（仅改写文本，不做反向映射、不改枚举）。 */
export const TAU_DISPLAY_LABEL: Record<Tau, TauDisplayLabel> = {
  episodic: 'episode',
  affective: 'emotion',
  procedural: 'skill',
  semantic: 'knowledge',
}

/**
 * 由唯一真源派生的展示标签：`RENAME[TAU_BY_MEMORY_KIND[kind]]`。
 *
 * 5 个 memory_kind → 4 个标签（`long_term` 与 `knowledge_card` 同为 `knowledge`）。
 */
export function displayLabelForMemoryKind(kind: MemoryKind): TauDisplayLabel {
  return TAU_DISPLAY_LABEL[TAU_BY_MEMORY_KIND[kind]]
}

/** 各 τ 的基线 rho0。 */
export const PGC_V6_RHO0_BY_TAU: Record<Tau, number> = {
  episodic: 0.70,
  affective: 0.75,
  procedural: 0.65,
  semantic: 0.60,
}

/** 疲劳抑制系数 κ。 */
export const PGC_V6_KAPPA_FATIGUE = 1.25

/** 各 τ 的刺激权重 α（行=状态维 a,c,d,f）。dot = α·s。 */
export const PGC_V6_ALPHA_BY_TAU: Record<Tau, PgcState4> = {
  episodic: { a: 0.90, c: 0.10, d: 0.00, f: -0.20 },
  affective: { a: 0.20, c: 0.80, d: 0.05, f: -0.15 },
  procedural: { a: 0.10, c: -0.10, d: 0.85, f: -0.25 },
  semantic: { a: 0.60, c: 0.05, d: 0.10, f: -0.10 },
}

export type ContradictionLevel = 'low' | 'medium' | 'high'

export interface PgcV6DecisionPolicy {
  contradiction: { high_severity_reject: boolean }
  severity_to_action: { low: PgcDecision, medium: PgcDecision, high: PgcDecision }
  thresholds: { commit_min_w: number, throttle_min_w: number }
  fatigue_defer: { if_fatigue_gt: number, defer_w_threshold: number }
  final_intensity_mapping: { mode: 'identity' }
  /** 把数值矛盾严重度映射到 low/medium/high 的阈值（半开区间 [0,medium_from) low 等）。 */
  severity_bands: { medium_from: number, high_from: number }
}

export const DEFAULT_PGC_V6_POLICY: PgcV6DecisionPolicy = {
  contradiction: { high_severity_reject: true },
  severity_to_action: { low: 'throttle', medium: 'throttle', high: 'reject' },
  thresholds: { commit_min_w: 0.55, throttle_min_w: 0.30 },
  fatigue_defer: { if_fatigue_gt: 0.70, defer_w_threshold: 0.45 },
  final_intensity_mapping: { mode: 'identity' },
  severity_bands: { medium_from: 0.33, high_from: 0.66 },
}

/**
 * v6 参数包（ρ0 / κ / α）。与阈值策略 `PgcV6DecisionPolicy` 分离，便于在**测试**里注入
 * 第 1 份参数（构造性零）作为 fixture，而不让它进入生产路径。生产路径只用 `PGC_V6_PARAMS_CASE4`。
 */
export interface PgcV6Params {
  rho0_by_tau: Record<Tau, number>
  kappa: number
  alpha_by_tau: Record<Tau, PgcState4>
}

/** 当前生产基线：第 4 份参数（case id = 4）。 */
export const PGC_V6_PARAMS_CASE4: PgcV6Params = {
  rho0_by_tau: PGC_V6_RHO0_BY_TAU,
  kappa: PGC_V6_KAPPA_FATIGUE,
  alpha_by_tau: PGC_V6_ALPHA_BY_TAU,
}

/** 当前在用的基线编号（用于审计回放：哪套参数产出了这次决策）。 */
export const PGC_V6_TAU_CASE_ID = 4

/**
 * commit 判定原因（按诊断优先级排序，见 `deriveV6CommitVerdict`）：
 * 1. `w_max_below_theta`  — 基线层面构造性零（最重要，必须能触发）
 * 2. `contradiction_high` — 高严重度矛盾
 * 3. `evidence_insufficient` — 证据不足（沿用现有阈值策略）
 * 4. `fatigue_deferred` — 疲劳推迟（defer ≠ reject，语义是推迟到离线巩固）
 * 5. `w_below_theta` — 状态依赖的不足
 * 6. `committed`
 */
export type CommitReason
  = | 'w_max_below_theta'
    | 'contradiction_high'
    | 'evidence_insufficient'
    | 'fatigue_deferred'
    | 'w_below_theta'
    | 'committed'

/** v6 门控写进快照与审计的中间量（规范第 4 份要求 replay minimums 含 computed_w）。 */
export interface PgcV6State {
  tau: Tau
  s: PgcState4
  rho0: number
  kappa: number
  /** dot = α·s。 */
  dot: number
  /** w_raw = rho0·(1+dot)·(1-κ·f)，未 clip。 */
  w_prime: number
  /** w = clip(w_raw, 0, 1)。 */
  w: number
  /** 闭式上界：全局 w_max（与当前疲劳无关）。 */
  w_max_global: number
  /** 闭式上界：给定当前疲劳 f_t 的 w_max。 */
  w_max_at_f: number
  /** 本次写入是否可能 commit（诊断项，区分「状态不好」与「参数不可能」）。 */
  commit_possible: boolean
  /** 见 `CommitReason`。 */
  commit_reason: CommitReason
  fatigue_deferred: boolean
  contradiction_level: ContradictionLevel
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
  /**
   * 规范第 4 份要求的 replay minimums 之一：审计必须能回溯到产生该决策的 pgc_policy_version。
   * 旧证据阈值策略与 v6 门控都填这里，便于统一回放。（可选以兼容不含版本的旧快照构造。）
   */
  pgc_policy_version?: string
  /** v6 四维状态门控结果（仅在提供 v6 状态时填充；不含时走既有纯证据阈值策略）。 */
  v6?: PgcV6State
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

// ============================================================================
// v6 写入门控：w(m, s_t) 与决策顺序
// ============================================================================

/**
 * 计算 v6 提交权重 w(m, s_t)。
 *
 *     tau  = TAU_BY_MEMORY_KIND[memory_kind]
 *     rho0 = rho0_by_tau[tau]
 *     dot  = α.a·s.a + α.c·s.c + α.d·s.d + α.f·s.f
 *     w_raw = rho0 · (1 + dot) · (1 - κ·s.f)
 *     w = clip(w_raw, 0, 1)
 */
export function computeV6CommitmentWeight(
  memory_kind: MemoryKind,
  s: PgcState4,
  policy: PgcV6DecisionPolicy = DEFAULT_PGC_V6_POLICY,
): { tau: Tau, rho0: number, kappa: number, dot: number, w_prime: number, w: number } {
  const tau = TAU_BY_MEMORY_KIND[memory_kind]
  const rho0 = PGC_V6_RHO0_BY_TAU[tau]
  const alpha = PGC_V6_ALPHA_BY_TAU[tau]
  const dot = alpha.a * s.a + alpha.c * s.c + alpha.d * s.d + alpha.f * s.f
  const w_prime = rho0 * (1 + dot) * (1 - PGC_V6_KAPPA_FATIGUE * s.f)
  const w = Math.min(1, Math.max(0, w_prime))
  void policy // 参数基线已内联为常量；policy 预留给未来把 α/κ/rho0 也参数化。
  return { tau, rho0, kappa: PGC_V6_KAPPA_FATIGUE, dot, w_prime, w }
}

/** 把数值矛盾严重度映射到 low/medium/high。 */
export function contradictionLevelFromSeverity(
  severity: number,
  policy: PgcV6DecisionPolicy = DEFAULT_PGC_V6_POLICY,
): ContradictionLevel {
  if (severity >= policy.severity_bands.high_from)
    return 'high'
  if (severity >= policy.severity_bands.medium_from)
    return 'medium'
  return 'low'
}

/**
 * 应用 v6 决策顺序（严格照规范）：
 *
 *     if contradiction_level == 'high'            -> reject
 *     else if s.f > 0.70 && w >= 0.45             -> defer
 *     else if w >= 0.55                           -> commit
 *     else if w >= 0.30                           -> throttle
 *     else                                        -> reject
 *
 * `final_intensity = w`（final_intensity_mapping.mode = 'identity'）。
 */
export function applyV6Decision(
  w: number,
  s: PgcState4,
  contradictionLevel: ContradictionLevel,
  policy: PgcV6DecisionPolicy = DEFAULT_PGC_V6_POLICY,
): { decision: PgcDecision, reason_codes: PgcReasonCode[], fatigue_deferred: boolean } {
  const reason_codes: PgcReasonCode[] = []
  let decision: PgcDecision
  let fatigue_deferred = false

  // 1) 高严重度矛盾优先于一切（即使 w=1）。
  if (policy.contradiction.high_severity_reject && contradictionLevel === 'high') {
    reason_codes.push('contradiction_detected')
    decision = policy.severity_to_action.high
  }
  // 2) 疲劳高且仍有较强提交意愿 ⇒ 延迟到离线巩固复审（而非直接 commit）。
  else if (s.f > policy.fatigue_defer.if_fatigue_gt && w >= policy.fatigue_defer.defer_w_threshold) {
    reason_codes.push('deferred_pending_review')
    decision = 'defer'
    fatigue_deferred = true
  }
  // 3) 达到 commit 阈值。
  else if (w >= policy.thresholds.commit_min_w) {
    reason_codes.push('sufficient_evidence')
    decision = 'commit'
  }
  // 4) 达到 throttle 阈值。
  else if (w >= policy.thresholds.throttle_min_w) {
    reason_codes.push('throttled_high_intensity')
    decision = 'throttle'
  }
  // 5) 不足 ⇒ reject。
  else {
    reason_codes.push('low_evidence')
    decision = 'reject'
  }

  return { decision, reason_codes, fatigue_deferred }
}

// ============================================================================
// v6 闭式 w_max 上界 + commit 判定（构造性零显式化）
// ============================================================================

/**
 * 闭式计算 v6 提交权重 w 的上界。
 *
 * w_raw = ρ₀(1 + α·s)(1 - κ·f)，s∈[0,1]^4。因 a/c/d 与 f 解耦：
 *   baseMax = 1 + max(α.a,0) + max(α.c,0) + max(α.d,0)      // 全取正项角点
 *   baseMin = 1 + min(α.a,0) + min(α.c,0) + min(α.d,0)      // 全取负项角点
 *   g(f) = max( (baseMax + α.f·f)(1 - κ·f),
 *               (baseMin + α.f·f)(1 - κ·f) )                // f 的上包络
 *   候选 f ∈ {0, 1, 各二次函数的顶点（若 A≠0 且落在 (0,1)}）
 *   w_max_global   = clip(ρ₀ · max g(f), 0, 1)
 *   w_max_at_f(f)  = clip(ρ₀ · g(f), 0, 1)                  // 给定当前疲劳的上界
 *
 * ⚠️ 只取 baseMax 会在 (1-κ·f) < 0（即 f > 1/κ）时低估——负乘子下最优角点是 baseMin。
 * 该区间正是高疲劳诊断区，故必须取两角点乘积的较大者，否则「上界」语义不成立。
 *
 * 入参 `params` 携带 ρ0/κ/α；生产路径传 `PGC_V6_PARAMS_CASE4`，测试可传第 1 份 fixture。
 */
export function computeV6WMaxBounds(
  tau: Tau,
  params: PgcV6Params = PGC_V6_PARAMS_CASE4,
  f?: number,
): { w_max_global: number, w_max_at_f: number | null } {
  const rho0 = params.rho0_by_tau[tau]
  const alpha = params.alpha_by_tau[tau]
  const kappa = params.kappa
  const af = alpha.f
  // a/c/d 在 (1 + Σ α_i·s_i) 里各自独立且线性 ⇒ 极值只在两个角点：
  //   baseMax = 1 + Σ max(α_i, 0)（全取正项）
  //   baseMin = 1 + Σ min(α_i, 0)（全取负项）
  // 乘子 (1-κf) > 0 时 baseMax 给出最大乘积；乘子 < 0 时反过来由 baseMin 给出。
  // ⇒ 取两个角点乘积的较大者，才能对任意 κ/α 都保持「上界」语义。
  // （只用 baseMax 会在 f > 1/κ 时低估，而该区间正是高疲劳诊断区。）
  const baseMax = 1 + Math.max(alpha.a, 0) + Math.max(alpha.c, 0) + Math.max(alpha.d, 0)
  const baseMin = 1 + Math.min(alpha.a, 0) + Math.min(alpha.c, 0) + Math.min(alpha.d, 0)
  const g = (fv: number) => {
    const k = 1 - kappa * fv
    return Math.max((baseMax + af * fv) * k, (baseMin + af * fv) * k)
  }
  // g 是两个二次函数的上包络 ⇒ 候选点 = 端点 + 两个二次函数各自的顶点。
  const candidates = [0, 1]
  if (af !== 0) {
    const A = -af * kappa
    for (const base of [baseMax, baseMin]) {
      const vertex = -((af - base * kappa)) / (2 * A)
      if (vertex > 0 && vertex < 1)
        candidates.push(vertex)
    }
  }
  let gMax = -Infinity
  for (const fv of candidates)
    gMax = Math.max(gMax, g(fv))
  const w_max_global = Math.min(1, Math.max(0, rho0 * gMax))
  const w_max_at_f = f === undefined ? null : Math.min(1, Math.max(0, rho0 * g(f)))
  return { w_max_global, w_max_at_f }
}

/**
 * 推导 commit 判定（诊断项，非逻辑门控）：
 *
 *   commit_possible ≡ (w_max_global ≥ θ) ∧ (contradiction_level ≠ 'high')
 *                     ∧ (证据充分) ∧ (w ≥ θ)
 *
 * `commit_reason` 按下方顺序取第一个命中者（区分「这次状态不好」与「这套参数根本不可能」）：
 *   1. w_max_below_theta  — 基线层面构造性零（最重要）
 *   2. contradiction_high
 *   3. evidence_insufficient
 *   4. fatigue_deferred   — 注意 defer ≠ reject
 *   5. w_below_theta
 *   6. committed
 */
export function deriveV6CommitVerdict(args: {
  w_max_global: number
  contradiction_level: ContradictionLevel
  evidence_sufficient: boolean
  decision: PgcDecision
  w: number
  theta?: number
}): { commit_possible: boolean, commit_reason: CommitReason } {
  const theta = args.theta ?? DEFAULT_PGC_V6_POLICY.thresholds.commit_min_w
  if (args.w_max_global < theta)
    return { commit_possible: false, commit_reason: 'w_max_below_theta' }
  if (args.contradiction_level === 'high')
    return { commit_possible: false, commit_reason: 'contradiction_high' }
  if (!args.evidence_sufficient)
    return { commit_possible: false, commit_reason: 'evidence_insufficient' }
  if (args.decision === 'defer')
    return { commit_possible: false, commit_reason: 'fatigue_deferred' }
  if (args.w < theta)
    return { commit_possible: false, commit_reason: 'w_below_theta' }
  return { commit_possible: true, commit_reason: 'committed' }
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

  // ---- v6 门控分支：仅当 read context 提供四维状态 s_t 时走 v6；否则走既有纯证据阈值策略 ----
  if (ctx.pgc_v6_state) {
    const s = ctx.pgc_v6_state
    const { tau, rho0, kappa, dot, w_prime, w } = computeV6CommitmentWeight(cand.memory_kind, s, DEFAULT_PGC_V6_POLICY)
    const { w_max_global, w_max_at_f } = computeV6WMaxBounds(tau, PGC_V6_PARAMS_CASE4, s.f)
    const level = contradictionLevelFromSeverity(contraSeverity)
    const { decision, reason_codes, fatigue_deferred } = applyV6Decision(w, s, level, DEFAULT_PGC_V6_POLICY)
    const hasEvidence = cand.evidence_ids.length > 0
    const evidence_sufficient = hasEvidence && evStrength >= 1
    const { commit_possible, commit_reason } = deriveV6CommitVerdict({
      w_max_global,
      contradiction_level: level,
      evidence_sufficient,
      decision,
      w,
    })
    const v6: PgcV6State = {
      tau,
      s: { ...s },
      rho0,
      kappa,
      dot,
      w_prime,
      w,
      w_max_global,
      w_max_at_f: w_max_at_f ?? w_max_global,
      commit_possible,
      commit_reason,
      fatigue_deferred,
      contradiction_level: level,
    }
    const snapshot: PgcStateSnapshot = { pgc_state_id, components, pgc_policy_version: policy.version, v6 }
    // final_intensity = w（final_intensity_mapping.mode = 'identity'）。
    return {
      memory_write_id: cand.memory_write_id,
      decision,
      final_intensity: w,
      reason_codes,
      expected_tests: expectedTestsFor(decision, reason_codes),
      pgc_state_snapshot: snapshot,
    }
  }

  const snapshot: PgcStateSnapshot = { pgc_state_id, components, pgc_policy_version: policy.version }

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
