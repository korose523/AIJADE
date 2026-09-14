/**
 * v7 §38 — 统一干预 API（基线与消融）。
 *
 * 动机（§1 痛点 5）：「无法做因果实验：缺少统一事件日志、状态快照、**固定种子、
 * 旁路和干预点**」。本模块补的正是后三项 —— 让消融从「改代码重跑」变成
 * 「声明一个可登记的干预计划」：
 *
 *   1. **干预点**：机制开关的单一权威清单（`INTERVENTION_POINTS`），覆盖 §38.1 记忆基线、
 *      §38.2 HAC 消融、§38.3 DGM 消融、§38.4 CDI 消融。未知开关一律拒绝（防拼写漂移静默生效）。
 *   2. **旁路**：把某机制整体替换为退化实现（如 `memory:window(8)`）。
 *   3. **固定种子 + 指纹**：`resolveIntervention(plan, seed)` 产出**规范化的**完整开关图与
 *      确定性指纹；相同 (plan, seed) ⇒ 相同指纹，故「这两次跑的是同一套配置」可被证明，
 *      而不是被声明。随机类消融（如 `hac_random_write` 随机同预算写入）经
 *      `interventionRng(seed)` 取数，同样是确定性的。
 *   4. **登记**：`registerIntervention(plan, seed)` 把干预计划落成一份 §38
 *      `ExperimentManifest` 条件并写入提交式 registry —— 消融因此是**被登记的**，
 *      与 `./experiment` 的可复现保证同一条链。
 *
 * 纯函数 + 无外部依赖；不介入记忆 durability/salience 的默认行为（H2c 兼容护盾），
 * 只负责描述与解析「这次跑的是哪套配置」。
 */

import type { ExperimentManifest } from './contracts'

import { fnv1a } from './contracts'
import { buildExperimentManifest, registerExperimentManifest } from './experiment'

/** 干预点所属机制组（对应 §38.1–38.4）。 */
export type InterventionGroup = 'memory_baseline' | 'hac' | 'dgm' | 'cdi'

export interface InterventionPoint {
  id: string
  group: InterventionGroup
  description: string
  /** 完整机制（A1 / CDI 完整）下的默认状态。 */
  defaultOn: boolean
}

/**
 * §38 干预点清单（单一权威来源）。
 *
 * 默认 = 我们的完整机制（内容显著性门控 + HAC 全开 + 双图 + 受约束身份）。
 * `hac_fix_transition` / `hac_random_write` / `dgm_llm_commit` 等属**消融/反模式**，默认关。
 */
export const INTERVENTION_POINTS: InterventionPoint[] = [
  // §38.1 记忆基线
  { id: 'long_term_memory', group: 'memory_baseline', description: '长期记忆（关闭 = B0 无长期记忆）', defaultOn: true },
  { id: 'memory_window', group: 'memory_baseline', description: '滑动窗口（B1）', defaultOn: false },
  { id: 'vector_write_all', group: 'memory_baseline', description: '向量检索 + 全写入（B2）', defaultOn: false },
  { id: 'salience_threshold', group: 'memory_baseline', description: '即时重要性阈值 / 内容显著性门控（B3）', defaultOn: true },
  { id: 'llm_reflection', group: 'memory_baseline', description: 'LLM 反思式记忆（B4）', defaultOn: false },
  { id: 'memory_budget', group: 'memory_baseline', description: '固定预算多类记忆（B5）', defaultOn: false },

  // §38.2 HAC 消融
  { id: 'hac_state', group: 'hac', description: '内生状态 z_t（关闭 = 去除内生状态）', defaultOn: true },
  { id: 'hac_homeostatic_error', group: 'hac', description: '稳态误差 e_t（关闭 = 去除稳态误差）', defaultOn: true },
  { id: 'hac_goal_utility', group: 'hac', description: '未来目标效用（关闭 = 去除未来目标效用）', defaultOn: true },
  { id: 'hac_active_replay', group: 'hac', description: '主动回放（§9.4）', defaultOn: true },
  { id: 'hac_retrieval_noise', group: 'hac', description: '检索退化代价 ξ（§9.5；关闭 = 去除噪声代价）', defaultOn: true },
  { id: 'hac_fix_transition', group: 'hac', description: '固定状态转移矩阵（消融：A/B/C 不再演化）', defaultOn: false },
  { id: 'hac_random_write', group: 'hac', description: '随机同预算写入（对照：保留条数相同但随机选）', defaultOn: false },

  // §38.3 DGM 消融
  { id: 'dgm_single_store', group: 'dgm', description: '退化为单一向量库（消融）', defaultOn: false },
  { id: 'dgm_dual_graph', group: 'dgm', description: '经历图与信念图分离（关闭 = 不分离）', defaultOn: true },
  { id: 'dgm_counter_evidence', group: 'dgm', description: '反证边（关闭 = 无反证）', defaultOn: true },
  { id: 'dgm_source_reliability', group: 'dgm', description: '来源可靠度（关闭 = 无可靠度）', defaultOn: true },
  { id: 'dgm_llm_commit', group: 'dgm', description: 'LLM 直接提交信念（反模式消融，默认关闭）', defaultOn: false },

  // §38.4 CDI 消融
  { id: 'cdi_identity', group: 'cdi', description: '身份层演化（关闭 = 静态人格）', defaultOn: true },
  { id: 'cdi_constraint', group: 'cdi', description: '‖Δp‖≤ε 等约束（关闭 = 自由人格演化）', defaultOn: true },
  { id: 'cdi_prompt_only', group: 'cdi', description: '仅角色提示词累积（消融）', defaultOn: false },
  { id: 'cdi_shadow_eval', group: 'cdi', description: '影子评测（关闭 = 无影子评测）', defaultOn: true },
]

const POINT_INDEX = new Map(INTERVENTION_POINTS.map(p => [p.id, p]))

export const DEFAULT_SWITCHES: Record<string, boolean> = Object.fromEntries(
  INTERVENTION_POINTS.map(p => [p.id, p.defaultOn]),
)

/**
 * 一份干预计划（基线或消融）。`switches` 是相对默认值的**覆写**，
 * 因此一次消融只需声明「改了什么」，可读性远好于全量 22 项。
 */
export interface InterventionPlan {
  id: string
  name: string
  description: string
  switches: Record<string, boolean>
  /** 旁路：把干预点整体替换为退化实现，键必须是 `INTERVENTION_POINTS` 中的 id，如 `{ long_term_memory: 'window(8)' }`。 */
  bypass?: Record<string, string>
}

/**
 * v7 §38 — 干预 API 的产品接入配置。
 *
 * 仅当 `enabled` 显式为 true 时，store 才会解析并持有干预配置（H2c 兼容：
 * 默认完全不持有，记忆 durability/salience 不受任何影响）。`plan` 为可选构造期
 * 即登记的基线/消融计划；省略则 store 仅回退至 `DEFAULT_SWITCHES`，仍可在运行时
 * 经 `applyIntervention(plan)` 登记。
 */
export interface InterventionConfig {
  enabled: boolean
  /** 固定种子（§38 可复现）。默认 0。 */
  seed?: number
  /** 构造即解析并登记的干预计划（基线或消融）；省略则运行时再登记。 */
  plan?: InterventionPlan
}

/** 解析后的干预：完整有效开关图 + 旁路 + 种子 + 确定性指纹。 */
export interface ResolvedIntervention {
  planId: string
  /** 全部干预点的**有效**状态（默认 ⊕ 覆写）。 */
  switches: Record<string, boolean>
  bypass: Record<string, string>
  seed: number
  /** 相同 (plan, seed) ⇒ 相同指纹 —— 「同一套配置」可被证明。 */
  fingerprint: string
}

/** §38.1 记忆基线（B0–B5）与 A1。 */
export const BASELINE_PLANS: InterventionPlan[] = [
  { id: 'B0', name: 'B0 无长期记忆', description: '旁路全部长期记忆', switches: { long_term_memory: false } },
  { id: 'B1', name: 'B1 滑动窗口', description: '仅保留最近窗口内的内容', switches: { long_term_memory: false, memory_window: true }, bypass: { long_term_memory: 'window(8)' } },
  { id: 'B2', name: 'B2 向量检索 + 全写入', description: '不筛选，全量写入后检索', switches: { vector_write_all: true, salience_threshold: false } },
  { id: 'B3', name: 'B3 即时重要性阈值', description: '按即时重要性阈值筛选', switches: { salience_threshold: true } },
  { id: 'B4', name: 'B4 LLM 反思式记忆', description: '由 LLM 反思决定保留', switches: { llm_reflection: true } },
  { id: 'B5', name: 'B5 固定预算多类记忆', description: '多类记忆 + 固定存储预算', switches: { memory_budget: true } },
  {
    id: 'A1',
    name: 'A1 HAC 完整模型',
    description: 'HAC 全开（我们的完整机制）—— 显式钉住全量配置，作为消融的对照基准',
    switches: {
      hac_state: true,
      hac_homeostatic_error: true,
      hac_goal_utility: true,
      hac_active_replay: true,
      hac_retrieval_noise: true,
      hac_fix_transition: false,
      hac_random_write: false,
    },
  },
]

/** §38.2 HAC 消融。 */
export const HAC_ABLATION_PLANS: InterventionPlan[] = [
  { id: 'hac-no-state', name: '去除内生状态', description: '冻结/移除 z_t', switches: { hac_state: false } },
  { id: 'hac-no-error', name: '去除稳态误差', description: 'e_t 不再驱动写入门控', switches: { hac_homeostatic_error: false } },
  { id: 'hac-no-goal', name: '去除未来目标效用', description: 'U_i 去掉未来目标项', switches: { hac_goal_utility: false } },
  { id: 'hac-no-replay', name: '去除主动回放', description: '不做 §9.4 主动回放', switches: { hac_active_replay: false } },
  { id: 'hac-no-noise', name: '去除检索噪声代价', description: '关闭 §9.5 检索退化代价', switches: { hac_retrieval_noise: false } },
  { id: 'hac-fix-transition', name: '固定状态转移', description: 'A/B/C 固定不演化', switches: { hac_fix_transition: true } },
  { id: 'hac-random-write', name: '随机同预算写入', description: '保留条数相同但随机选择（需固定种子）', switches: { hac_random_write: true } },
]

/** §38.3 DGM 消融。 */
export const DGM_ABLATION_PLANS: InterventionPlan[] = [
  { id: 'dgm-single-store', name: '单一向量库', description: '退化为单一向量库', switches: { dgm_single_store: true } },
  { id: 'dgm-no-separation', name: '经历与信念不分离', description: '关闭双图分离', switches: { dgm_dual_graph: false } },
  { id: 'dgm-no-counter', name: '无反证边', description: '不接受/不记录反证', switches: { dgm_counter_evidence: false } },
  { id: 'dgm-no-reliability', name: '无来源可靠度', description: '来源一律同等可信', switches: { dgm_source_reliability: false } },
  { id: 'dgm-llm-commit', name: 'LLM 直接提交信念', description: '反模式：绕过验证器直接入库', switches: { dgm_llm_commit: true } },
]

/** §38.4 CDI 消融。 */
export const CDI_ABLATION_PLANS: InterventionPlan[] = [
  { id: 'cdi-static', name: '静态人格', description: '身份层不演化', switches: { cdi_identity: false } },
  { id: 'cdi-free', name: '自由人格演化', description: '去掉漂移界等约束', switches: { cdi_constraint: false } },
  { id: 'cdi-prompt-only', name: '仅角色提示词累积', description: '退化为提示词堆叠', switches: { cdi_prompt_only: true } },
  { id: 'cdi-no-shadow', name: 'CDI 无影子评测', description: '不做影子评测即提交', switches: { cdi_shadow_eval: false } },
  {
    id: 'cdi-full',
    name: 'CDI 完整机制',
    description: '三层身份 + 约束 + 影子评测 —— 显式钉住全量配置，作为消融的对照基准',
    switches: {
      cdi_identity: true,
      cdi_constraint: true,
      cdi_shadow_eval: true,
      cdi_prompt_only: false,
    },
  },
]

export const ALL_ABLATION_PLANS: InterventionPlan[] = [
  ...BASELINE_PLANS,
  ...HAC_ABLATION_PLANS,
  ...DGM_ABLATION_PLANS,
  ...CDI_ABLATION_PLANS,
]

/** 规范化序列化，保证开关顺序不影响指纹。 */
function canonical(plan: InterventionPlan, switches: Record<string, boolean>, seed: number): string {
  const sw = Object.keys(switches).sort().map(k => `${k}=${switches[k] ? 1 : 0}`).join(',')
  const bp = Object.keys(plan.bypass ?? {}).sort().map(k => `${k}=${(plan.bypass as Record<string, string>)[k]}`).join(',')
  return `${plan.id}|${sw}|${bp}|seed=${seed}`
}

/**
 * 校验干预计划：未知干预点 / 未知旁路点 / 空覆写 均拒。
 * 纯函数，返回 `{ok}` / `{ok:false,reason}`，永不抛错。
 */
export function validateInterventionPlan(
  plan: InterventionPlan,
): { ok: true } | { ok: false, reason: string } {
  if (!plan.id)
    return { ok: false, reason: 'InterventionPlan requires an id' }
  if (Object.keys(plan.switches ?? {}).length === 0)
    return { ok: false, reason: 'InterventionPlan must change ≥1 switch (an ablation must ablate something)' }
  for (const id of Object.keys(plan.switches)) {
    if (!POINT_INDEX.has(id))
      return { ok: false, reason: `Unknown intervention point "${id}"` }
  }
  for (const id of Object.keys(plan.bypass ?? {})) {
    if (!POINT_INDEX.has(id))
      return { ok: false, reason: `Unknown bypass point "${id}"` }
  }
  return { ok: true }
}

/**
 * 解析干预计划 → 完整有效开关图 + 指纹。
 * 与默认状态相同的覆写被保留但不影响指纹之外的语义（指纹只看有效值）。
 */
export function resolveIntervention(plan: InterventionPlan, seed = 0): ResolvedIntervention {
  const v = validateInterventionPlan(plan)
  if (!v.ok)
    throw new Error(`InterventionPlan "${plan.id}" invalid: ${v.reason}`)
  if (!Number.isFinite(seed))
    throw new Error('Intervention requires a finite seed (reproducibility)')
  const switches: Record<string, boolean> = { ...DEFAULT_SWITCHES, ...plan.switches }
  return {
    planId: plan.id,
    switches,
    bypass: { ...plan.bypass },
    seed,
    fingerprint: fnv1a(canonical(plan, switches, seed)),
  }
}

/** 查询某干预点在解析结果中是否启用；未知点按「未启用」处理（不静默放行）。 */
export function isEnabled(resolved: ResolvedIntervention, pointId: string): boolean {
  return resolved.switches[pointId] === true
}

/** 取旁路实现标识（未旁路则为 undefined）。 */
export function bypassOf(resolved: ResolvedIntervention, pointId: string): string | undefined {
  return resolved.bypass[pointId]
}

/** mulberry32：确定性 RNG，供随机类消融（如 `hac_random_write`）在固定种子下取数。 */
export function interventionRng(seed: number): () => number {
  let s = seed >>> 0
  return () => {
    s = (s + 0x6D2B79F5) >>> 0
    let t = Math.imul(s ^ s >>> 15, 1 | s)
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t
    return ((t ^ t >>> 14) >>> 0) / 4294967296
  }
}

export interface RegisterInterventionOptions {
  /** 固定种子（§38 可复现）。默认 0。 */
  seed?: number
  /** 该消融承诺报告的指标；默认 `['intervention.fingerprint']`。 */
  metrics?: string[]
  /** registry 路径；默认提交式 `eval/experiments.registry.json`（测试可指向临时文件）。 */
  registryPath?: string
}

export interface RegisteredIntervention {
  manifest: ExperimentManifest
  resolved: ResolvedIntervention
}

/**
 * 把干预计划**登记**为一份 §38 `ExperimentManifest` 条件并写入 registry。
 * 这样消融不是「改代码重跑」，而是「声明 + 登记 + 可复现」。
 */
export function registerIntervention(
  plan: InterventionPlan,
  opts: RegisterInterventionOptions = {},
): RegisteredIntervention {
  const seed = opts.seed ?? 0
  const resolved = resolveIntervention(plan, seed)
  const manifest = buildExperimentManifest({
    id: `intervention:${plan.id}`,
    name: plan.name,
    seed,
    conditions: [{
      name: plan.id,
      description: plan.description,
      params: { switches: resolved.switches, bypass: resolved.bypass, fingerprint: resolved.fingerprint },
    }],
    metrics: opts.metrics ?? ['intervention.fingerprint'],
    notes: `§38 intervention plan "${plan.id}" (${plan.description}). Fingerprint ${resolved.fingerprint} — identical (plan, seed) ⇒ identical configuration.`,
  })
  registerExperimentManifest(manifest, opts.registryPath)
  return { manifest, resolved }
}
