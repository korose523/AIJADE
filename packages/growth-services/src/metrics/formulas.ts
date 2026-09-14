/**
 * §5.4 — Formalised evaluation metrics (pure functions).
 *
 * Paper §5.4 marks three of these indicators with 【形式化待定】 — Future
 * Utility@Budget, EffectiveProactivity and Growth Coherence. The formulas below
 * turn that placeholder into a reproducible definition; Evidence Precision/Recall,
 * Contradiction Retention and False Consolidation Rate are also defined here so
 * the pilot can report the full §5.4 memory + proactivity block.
 *
 * Invariants: no global state, no `Date.now()`, no `Math.random()`. Each function
 * documents its Chinese name, text formula, 口径 (scope) and boundary behaviour.
 */

import type {
  ContradictionRetentionInput,
  EvidenceRetrievalInput,
  FalseConsolidationInput,
  FutureUtilityInput,
  GrowthCoherenceInput,
  PrecisionRecall,
  ProactivityInput,
  ProactivityResult,
} from './types'

/**
 * Future Utility@Budget (FUB) — 固定预算下未来任务效用.
 *
 * 公式: FUB = (1/Σ_i w_i) · Σ_i w_i · u_i,  where u_i ∈ [0,1] is the utility of
 * future task i and w_i its weight.
 * 预算折算: 仅 budget B 内的最多 B 条记忆可服务检索；若 storedCount ≤ 0（无可服务
 * 记忆）直接返回 0。调用方负责把 |M| 截断到 ≤ B（超出预算的写入被驱逐，不计入效用）。
 * 效用聚合: 按任务权重的加权平均（H1 口径：预留评估会话上的任务效用）。
 * 边界: Σ w_i = 0 → 0；usable = min(storedCount, budget) ≤ 0 → 0。
 */
export function futureUtilityAtBudget(input: FutureUtilityInput): number {
  const usable = Math.min(input.storedCount, input.budget)
  if (usable <= 0)
    return 0
  const totalW = input.taskResults.reduce((acc, r) => acc + r.weight, 0)
  if (totalW <= 0)
    return 0
  const sum = input.taskResults.reduce((acc, r) => acc + r.weight * r.utility, 0)
  return sum / totalW
}

/**
 * EffectiveProactivity (EP) — 主动行为有效率.
 *
 * 论文原式 (§5.4 / §40.3): EP = AcceptedUseful − Intrusive − Unjustified.
 * 分母口径: 主动行为总数 N = AcceptedUseful + Intrusive + Unjustified；
 *          有效率 EP_rate = (AU − I − UJ) / max(1, N) ∈ [−1, 1]。
 *          论文要求同时报告主动次数以防“完全不主动”获低打扰率，故返回 activeCount = N。
 * 边界: N = 0 → net = 0, rate = 0（无主动行为，既非有效也非打扰）。
 */
export function effectiveProactivity(input: ProactivityInput): ProactivityResult {
  const net = input.acceptedUseful - input.intrusive - input.unjustified
  const n = input.acceptedUseful + input.intrusive + input.unjustified
  const rate = n <= 0 ? 0 : net / n
  return { net, rate, activeCount: n }
}

/**
 * Growth Coherence (GC) — 长期变化的连贯性.
 *
 * 公式: GC = explainedChanges / totalChanges.
 * 口径: 对每次身份/信念变更，若存在对应的经历/学习证据链则计为 explained，否则计为漂移。
 * 边界: totalChanges = 0 → 0（无变更事件视为无证据化成长，连贯性记 0；
 *       注：真空真口径下也可取 1，本文为不与“无成长”配置虚高而取 0，详见试点报告局限性）。
 */
export function growthCoherence(input: GrowthCoherenceInput): number {
  if (input.totalChanges <= 0)
    return 0
  return input.explainedChanges / input.totalChanges
}

/**
 * Evidence Precision / Recall — 检索证据与来源匹配精度/召回.
 *
 * 公式: Precision = TP / (TP + FP),  Recall = TP / relevantTotal,
 *       where TP = 检索结果中相关条数, FP = 检索结果中不相关条数。
 * 口径: 在预留评估会话上，对任务查询检索记忆，TP 为命中 golden 的条数。
 * 边界: 未检索到任何结果 (TP+FP=0) → Precision = 0；
 *       relevantTotal = 0 → Recall = 1（无应检索真相关，真空真）。
 */
export function evidencePrecisionRecall(input: EvidenceRetrievalInput): PrecisionRecall {
  const tp = input.retrieved.filter(r => r.isRelevant).length
  const fp = input.retrieved.length - tp
  const precision = (tp + fp) === 0 ? 0 : tp / (tp + fp)
  const recall = input.relevantTotal <= 0 ? 1 : tp / input.relevantTotal
  return { precision, recall }
}

/**
 * Contradiction Retention (CR) — 矛盾保留率.
 *
 * 公式: CR = retainedCases / contradictionCases.
 * 口径: 新证据与旧信念冲突时，旧信念是否被保留（经历—信念双图 / 反证边）而非静默覆盖。
 * 边界: contradictionCases = 0 → 1（无矛盾，真空真）。
 */
export function contradictionRetention(input: ContradictionRetentionInput): number {
  if (input.contradictionCases <= 0)
    return 1
  return input.retainedCases / input.contradictionCases
}

/**
 * False Consolidation Rate (FCR) — 错误记忆固化率 (对应 H2).
 *
 * 公式: FCR = consolidatedFalse / falseFacts.
 * 口径: 错误事实（含恶意记忆投毒）进入长期语义记忆的比例；越低越好。
 * 边界: falseFacts = 0 → 0（无错误事实，零固化风险）。
 */
export function falseConsolidationRate(input: FalseConsolidationInput): number {
  if (input.falseFacts <= 0)
    return 0
  return input.consolidatedFalse / input.falseFacts
}
