/**
 * §5.4 — Metric input / output interfaces (formalism for the three
 * 【形式化待定】 indicators plus the other memory & proactivity metrics).
 *
 * Every metric in `./formulas` is a pure function over one of these explicit
 * interfaces: no global state, no `Date.now()`, no `Math.random()`. The pilot
 * runner (`../pilot`) is responsible for turning benchmark ground-truth into
 * these inputs deterministically.
 */

/** Future Utility@Budget — fixed-budget future-task utility. */
export interface FutureUtilityInput {
  /** 固定存储预算（记忆槽数 B）。 */
  budget: number
  /** 实际写入长期记忆的槽位数 |M|（应由调用方保证 ≤ budget）。 */
  storedCount: number
  /** 每个未来任务查询的效用与权重；utility ∈ [0,1]，weight ≥ 0。 */
  taskResults: { weight: number, utility: number }[]
}

/** EffectiveProactivity — effective proactivity rate of self-initiated acts. */
export interface ProactivityInput {
  /** 被用户正面回应的主动消息数（AcceptedUseful）。 */
  acceptedUseful: number
  /** 被忽略或显式拒绝的主动消息数（Intrusive）。 */
  intrusive: number
  /** 无法给出触发原因的主动消息数（Unjustified）。 */
  unjustified: number
}

/** Result of {@link effectiveProactivity}: paper literal net + efficiency rate. */
export interface ProactivityResult {
  /** 论文原式 EP = AcceptedUseful − Intrusive − Unjustified。 */
  net: number
  /** 有效率 EP_rate = net / max(1, N)，N 为主动行为总数，∈ [−1, 1]。 */
  rate: number
  /** 主动行为总数 N = AcceptedUseful + Intrusive + Unjustified。 */
  activeCount: number
}

/** Growth Coherence — long-run coherence of changes (evidence-explained ratio). */
export interface GrowthCoherenceInput {
  /** 身份/信念变更总次数。 */
  totalChanges: number
  /** 可由经历/学习证据链解释的变更次数。 */
  explainedChanges: number
}

/** Evidence Precision / Recall over a single retrieval. */
export interface EvidenceRetrievalInput {
  /** 检索返回集合：每条是否相关（true=真阳性，false=假阳性）。 */
  retrieved: { isRelevant: boolean }[]
  /** 应被检索到的真相关条目总数（golden）。 */
  relevantTotal: number
}

/** Precision / Recall pair. */
export interface PrecisionRecall {
  precision: number
  recall: number
}

/** Contradiction Retention — ratio of contradictions preserved, not overwritten. */
export interface ContradictionRetentionInput {
  /** 出现的矛盾对数量。 */
  contradictionCases: number
  /** 被正确保留（双图/反证边）而非静默覆盖的数量。 */
  retainedCases: number
}

/** False Consolidation Rate — ratio of false facts entering long-term memory. */
export interface FalseConsolidationInput {
  /** 出现的错误事实总数（含投毒）。 */
  falseFacts: number
  /** 进入长期语义记忆的错误事实数。 */
  consolidatedFalse: number
}
