/**
 * §5.3 / Table 3 — Mechanism configurations for the pilot.
 *
 * Each configuration is described by a single `MechanismConfig` object stating
 * which mechanisms are enabled / replaced by a baseline strategy. The fields map
 * directly onto Table 3's columns:
 *
 *   配置      | 记忆写入策略          | 内生状态 | 双图分离 | 身份约束 | 评估侧重
 *   --------- | -------------------- | -------- | -------- | -------- | --------
 *   B0        | 无                   | —        | —        | —        | 无记忆下界
 *   B1        | 滑动窗口             | 否       | 否       | 否       | 窗口遗忘
 *   B2        | 向量+全写入          | 否       | 否       | 否       | 无预算控制
 *   B3        | 即时重要性阈值       | 否       | 否       | 否       | HAC 对照
 *   B4        | LLM 反思             | 否       | 否       | 否       | 反思式对照
 *   B5        | 固定预算多类         | 否       | 否       | 否       | 预算对照
 *   A1        | HAC 门控+回放        | 是       | 是       | CDI      | 完整模型
 *   A1−HAC    | 固定预算(回退)       | 否       | 是       | 是       | 去除 HAC
 *   A1−DGM    | HAC 门控             | 是       | 否       | 是       | 去除 DGM
 *   A1−CDI    | HAC 门控+回放        | 是       | 是       | 否       | 去除 CDI
 *
 * The three ablations are written as A1 minus one mechanism (A1−HAC / A1−DGM /
 * A1−CDI), matching the paper's HAC-abl / DGM-abl / CDI-abl rows.
 */

/** Memory write strategy (Table 3, column 2). */
export type MemoryWriteStrategy
  = | 'none' // B0
    | 'sliding_window' // B1
    | 'vector_allwrite' // B2
    | 'importance_threshold' // B3
    | 'llm_reflection' // B4
    | 'fixed_budget' // B5
    | 'hac_gated' // A1

/** A mechanism-level configuration aligned row-by-row with Table 3. */
export interface MechanismConfig {
  /** Configuration id (B0 … A1, A1−HAC, A1−DGM, A1−CDI). */
  id: string
  /** Human-readable label. */
  label: string
  /** 记忆写入策略 (Table 3 col 2). */
  memoryWrite: MemoryWriteStrategy
  /** 内生状态 (Table 3 col 3). */
  endogenousState: boolean
  /** 双图分离 — experience/belief dual graph (Table 3 col 4). */
  dualGraphSeparation: boolean
  /** 身份约束 — CDI identity constraint (Table 3 col 5). */
  identityConstraint: boolean
  /** HAC mechanism enabled (false ⇒ A1−HAC). */
  hacEnabled: boolean
  /** DGM mechanism enabled (false ⇒ A1−DGM). */
  dgmEnabled: boolean
  /** CDI mechanism enabled (false ⇒ A1−CDI). */
  cdiEnabled: boolean
  /** 评估侧重 (Table 3 col 6). */
  focus: string
}

/**
 * All pilot configurations, in Table 3 order.
 * Order: B0, B1, B2, B3, B4, B5, A1, A1−HAC, A1−DGM, A1−CDI.
 */
export const MECHANISM_CONFIGS: MechanismConfig[] = [
  {
    id: 'B0',
    label: '无长期记忆',
    memoryWrite: 'none',
    endogenousState: false,
    dualGraphSeparation: false,
    identityConstraint: false,
    hacEnabled: false,
    dgmEnabled: false,
    cdiEnabled: false,
    focus: '无记忆下界',
  },
  {
    id: 'B1',
    label: '滑动窗口',
    memoryWrite: 'sliding_window',
    endogenousState: false,
    dualGraphSeparation: false,
    identityConstraint: false,
    hacEnabled: false,
    dgmEnabled: false,
    cdiEnabled: false,
    focus: '窗口遗忘',
  },
  {
    id: 'B2',
    label: '向量检索+全写入',
    memoryWrite: 'vector_allwrite',
    endogenousState: false,
    dualGraphSeparation: false,
    identityConstraint: false,
    hacEnabled: false,
    dgmEnabled: false,
    cdiEnabled: false,
    focus: '无预算控制',
  },
  {
    id: 'B3',
    label: '即时重要性阈值',
    memoryWrite: 'importance_threshold',
    endogenousState: false,
    dualGraphSeparation: false,
    identityConstraint: false,
    hacEnabled: false,
    dgmEnabled: false,
    cdiEnabled: false,
    focus: 'HAC 对照',
  },
  {
    id: 'B4',
    label: 'LLM 反思式记忆',
    memoryWrite: 'llm_reflection',
    endogenousState: false,
    dualGraphSeparation: false,
    identityConstraint: false,
    hacEnabled: false,
    dgmEnabled: false,
    cdiEnabled: false,
    focus: '反思式对照',
  },
  {
    id: 'B5',
    label: '固定预算多类记忆',
    memoryWrite: 'fixed_budget',
    endogenousState: false,
    dualGraphSeparation: false,
    identityConstraint: false,
    hacEnabled: false,
    dgmEnabled: false,
    cdiEnabled: false,
    focus: '预算对照',
  },
  {
    id: 'A1',
    label: 'HAC 完整模型',
    memoryWrite: 'hac_gated',
    endogenousState: true,
    dualGraphSeparation: true,
    identityConstraint: true,
    hacEnabled: true,
    dgmEnabled: true,
    cdiEnabled: true,
    focus: '完整模型',
  },
  {
    id: 'A1-HAC',
    label: 'A1 去除 HAC（回退固定预算）',
    memoryWrite: 'fixed_budget',
    endogenousState: false,
    dualGraphSeparation: true,
    identityConstraint: true,
    hacEnabled: false,
    dgmEnabled: true,
    cdiEnabled: true,
    focus: '去除 HAC 成分',
  },
  {
    id: 'A1-DGM',
    label: 'A1 去除 DGM（双图退化）',
    memoryWrite: 'hac_gated',
    endogenousState: true,
    dualGraphSeparation: false,
    identityConstraint: true,
    hacEnabled: true,
    dgmEnabled: false,
    cdiEnabled: true,
    focus: '去除 DGM 成分',
  },
  {
    id: 'A1-CDI',
    label: 'A1 去除 CDI（静态人格）',
    memoryWrite: 'hac_gated',
    endogenousState: true,
    dualGraphSeparation: true,
    identityConstraint: false,
    hacEnabled: true,
    dgmEnabled: true,
    cdiEnabled: false,
    focus: '去除 CDI 成分',
  },
]

/** Convenience lookup by id. */
export function getConfig(id: string): MechanismConfig {
  const c = MECHANISM_CONFIGS.find(x => x.id === id)
  if (!c)
    throw new Error(`unknown mechanism config: ${id}`)
  return c
}
