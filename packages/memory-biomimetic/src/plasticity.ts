import type { ContentSalience, GatingCoefficients, PhysiologicalState, PhysiologicalStateV3, PresentationModulation } from './types'

import { NEUTRAL_PRESENTATION } from './types'

/**
 * `PlasticityGate` — the **only** interface L3 (physiology / super-persona)
 * exposes to L4 (memory) and L5 (action).
 *
 * 出处与理由：
 * - v3 §1「关键设计约束」：L3 对外只暴露一个 `PlasticityGate` 结构体。
 * - v3 §2.3 / v4 §5.4：六个字段**全部有界**。无界的激素调制必然导致数值漂移。
 * - v3 §7：退化路径 = gate 全部返回恒等值 → 变成普通长期记忆体，**这恰好就是
 *   消融实验的对照组**。
 * - v3 §5：`retrieval_noise` 是反直觉但必要的。如果生理状态只能让系统变好、
 *   不能让它变差，那「生理门控」就不是机制，是增益开关。
 *
 * v2 / P2 重要变更：记忆门控现在由**内容显著性**驱动（见 `deriveGateFromContent`），
 * 激素只通过 `derivePresentationModulation` 影响表达，且可经 `physiology.enabled`
 * 关闭为中性。本 `PlasticityGate` 接口与激素版 `deriveGate` 仍保留作兼容/审计用。
 */
export interface PlasticityGate {
  /** 巩固增益 ← 内容显著性 × surprise。v3 §2.3 界 [0.2, 3.0] */
  consolidationGain: number
  /** 衰减倍率 ← (1 − 显著性)。显著性越高忘得越慢。界 [0.5, 4.0] */
  decayMultiplier: number
  /** 检索噪声 ← novelty（小）。界 [0.0, 0.3] */
  retrievalNoise: number
  /** 心境一致召回偏置权重 ← socialSalience。界 [0.0, 1.0] */
  moodCongruenceWeight: number
  /** 社交记忆加成 ← socialSalience。界 [1.0, 2.0] */
  socialBonus: number
  /** 探索温度 ← novelty（拓宽候选池）。界 [0.0, 1.2] */
  explorationTemperature: number
}

export const GATE_BOUNDS: Record<keyof PlasticityGate, { min: number, max: number }> = {
  consolidationGain: { min: 0.2, max: 3.0 },
  decayMultiplier: { min: 0.5, max: 4.0 },
  retrievalNoise: { min: 0.0, max: 0.3 },
  moodCongruenceWeight: { min: 0.0, max: 1.0 },
  socialBonus: { min: 1.0, max: 2.0 },
  explorationTemperature: { min: 0.0, max: 1.2 },
}

export const GATE_KEYS = Object.keys(GATE_BOUNDS) as (keyof PlasticityGate)[]

/**
 * 恒等门控 = 消融对照组（v3 §7）。
 *
 * 所有增益为 1、所有偏置/噪声为 0。系统退化为「普通长期记忆体」。
 */
export const NEUTRAL_GATE: PlasticityGate = Object.freeze({
  consolidationGain: 1,
  decayMultiplier: 1,
  retrievalNoise: 0,
  moodCongruenceWeight: 0,
  socialBonus: 1,
  explorationTemperature: 0,
})

function clamp01(x: number): number {
  return Math.min(1, Math.max(0, x))
}

/** 把 gate 夹回 v3 §2.3 的界内。任何调制都不得越界。 */
export function clampGate(g: PlasticityGate): PlasticityGate {
  const out = {} as PlasticityGate
  for (const k of GATE_KEYS) {
    const { min, max } = GATE_BOUNDS[k]
    out[k] = Math.min(max, Math.max(min, g[k]))
  }
  return out
}

/** 是否恒等（用于断言「消融对照组确实是中性」）。 */
export function isNeutralGate(g: PlasticityGate): boolean {
  return GATE_KEYS.every(k => Math.abs(g[k] - NEUTRAL_GATE[k]) < 1e-9)
}

/**
 * 内容显著性 → gate（v2 / P2 的核心）。
 *
 * 记忆的动态现在完全由**内容**驱动，不再由激素驱动。中性内容
 * (salience=0, socialSalience=0, novelty=0) 精确等于 `NEUTRAL_GATE` ——
 * 这正是「去掉内容门控 = 换一个返回值」的消融语义。
 *
 * - consolidationGain: 1 + 2·salience   (中性→1, 满→3, 界内)
 * - decayMultiplier:   1 − 0.5·salience  (中性→1; 越显著衰减越慢; 下界 0.5)
 * - retrievalNoise:    0.3·novelty       (中性→0)
 * - moodCongruenceWeight / socialBonus: 来自 socialSalience
 * - explorationTemperature: 1.2·novelty
 *
 * 注：记忆检索里的实际衰减率另由 `forgetting.retrievalStrength` 的
 * `decayExponent(salience, …)` 决定；此处 gate.decayMultiplier 仅为完整 gate 表示。
 */
export function deriveGateFromContent(sal: ContentSalience, surprise = 0.5): PlasticityGate {
  const s = clamp01(sal.salience)
  const soc = clamp01(sal.socialSalience)
  const nov = clamp01(sal.novelty)
  return clampGate({
    consolidationGain: 1 + 2 * s * (0.5 + 0.5 * clamp01(surprise)),
    decayMultiplier: 1 - 0.5 * s,
    retrievalNoise: 0.3 * nov,
    moodCongruenceWeight: soc,
    socialBonus: 1 + soc,
    explorationTemperature: 1.2 * nov,
  })
}

/**
 * 透明公式：激素状态 → gate（旧版；仅作兼容/审计，已不被 store 用于记忆门控）。
 *
 * v4 §5.4：全部值有界，并由可版本化函数从 `StateSnapshot` 映射。
 */
export function deriveGate(state: PhysiologicalState, surprise = 0.5): PlasticityGate {
  const intimacy = state.intimacy ?? 0
  const salience = clamp01(state.dopamine) * (0.5 + 0.5 * clamp01(surprise))
  return clampGate({
    consolidationGain: 0.2 + 2.8 * salience,
    decayMultiplier: 0.5 + 3.5 * clamp01(state.cortisol),
    retrievalNoise: 0.3 * clamp01(state.cortisol),
    moodCongruenceWeight: clamp01(state.serotonin),
    socialBonus: 1 + clamp01(state.oxytocin) * clamp01(intimacy),
    explorationTemperature: 1.2 * clamp01(state.adrenaline),
  })
}

/**
 * 兼容桥：把既有的 `GatingCoefficients`（P1/P1.5 的消融变量）映射为 gate。
 *
 * 关键性质：**`NO_GATING`（内容系数全 0）对任意生理状态都精确等于 `NEUTRAL_GATE`** ——
 * 消融对照组保持干净。内容系数非 0 时，退化为激素版 `deriveGate` 供审计/两阶段遗忘
 * （lifecycle）使用；该路径不影响 v2 的记忆门控（记忆门控走 `deriveGateFromContent`）。
 */
export function gateFromCoefficients(
  c: GatingCoefficients,
  state: PhysiologicalState,
): PlasticityGate {
  const isNeutral = c.kSalience === 0 && c.kSocial === 0 && c.kNovelty === 0
  if (isNeutral)
    return NEUTRAL_GATE
  return deriveGate(state)
}

/**
 * 表达层调制（v2 / P2）：L3 激素 → 仅影响「怎么说」。
 *
 * 当 `enabled === false` 时返回 {@link NEUTRAL_PRESENTATION}，对记忆**零**影响。
 * 三层状态（trait / mood / transient）加权得到 warmth / verbosity / hesitation /
 * energy，全部有界。
 */
export function derivePresentationModulation(
  state: PhysiologicalStateV3,
  enabled: boolean,
): PresentationModulation {
  if (!enabled)
    return NEUTRAL_PRESENTATION
  const { mood, transient } = state
  const warmth = 0.5
    + 0.25 * (mood.oxytocin + transient.oxytocin - 1)
    + 0.15 * (mood.serotonin - 0.5)
  const verbosity = 0.5
    + 0.30 * (mood.dopamine - 0.5)
    + 0.20 * (transient.adrenaline - 0.5)
  const hesitation = 0.40 * (mood.cortisol - 0.5)
    + 0.30 * (transient.cortisol - 0.5)
  const energy = 0.5
    + 0.25 * (transient.adrenaline - 0.5)
    + 0.15 * (mood.dopamine - 0.5)
  const clamp = (x: number): number => Math.min(1, Math.max(0, x))
  return {
    warmth: clamp(warmth),
    verbosity: clamp(verbosity),
    hesitation: clamp(hesitation),
    energy: clamp(energy),
  }
}

/**
 * 确定性哈希 → [0,1)。
 *
 * 检索噪声必须是**可复现**的：用 Math.random 会让同一次实验两次运行给出不同
 * 排序，直接摧毁可复现性保证。故用 FNV-1a 对 (key) 取哈希。
 */
export function deterministicUnit(key: string): number {
  let h = 0x811C9DC5
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h / 0x100000000
}

/**
 * 注入检索噪声（v3 §5 检索管线第三步）。
 *
 * score ← score · (1 − noise · u)，u 由 (key) 确定性决定。
 * noise ≤ 0.3，所以最多让分数降低 30%，且**同一记忆在同一状态下每次都降同样多**。
 */
export function applyRetrievalNoise(
  score: number,
  key: string,
  noise: number,
): number {
  if (noise <= 0)
    return score
  const u = deterministicUnit(key)
  return score * (1 - noise * u)
}
