/**
 * personality-lpm — AIJADE 超人格维度（"超人格 LPM"）。
 *
 * 设计稿产物：本节内容提炼自《AIJADE v9 角色背景设计文档（角色圣经）》§9.1
 * 的六个"超人格维度"。本文件是设计文档的代码化，**不是**实验测量结论——
 * 凡取值均由 §1.3 三条不变量 + §9.2 推导而来，未在真实对话中被标定过。
 *
 * 六个维度均为 [0,1] 连续值，供渲染器/调度器做确定性映射（不随机抖动）。
 */

/** 超人格维度键。声明顺序即 UI 展示顺序。 */
export interface PersonalityLpm {
  /** 语言语气：温暖/肯定的强度（高=更柔和、更在意在意）。 */
  languageTone: number
  /** 表达预算：一次对话最多输出的情绪确认/解释深度（高=更外露）。 */
  expressivenessBudget: number
  /** 风险诚实度：宁可少说也不把感受当事实（高=更克制、更证据优先）。 */
  riskTruthfulness: number
  /** 自主尊重：可以建议但不裁判（高=更把决定权留给用户）。 */
  autonomyRespect: number
  /** 可回放性：把承诺转成可回放计划（高=更强调可追踪的下一步）。 */
  replayability: number
  /** 好奇边界：好奇但不侵入（高=更主动追问，低=更克制不打探）。 */
  curiosityLimits: number
}

/** UI 展示顺序 = 声明顺序。 */
export const PERSONALITY_LPM_DIMS: readonly (keyof PersonalityLpm)[] = [
  'languageTone',
  'expressivenessBudget',
  'riskTruthfulness',
  'autonomyRespect',
  'replayability',
  'curiosityLimits',
]

/** 英文展示名。 */
export const PERSONALITY_LPM_LABELS: Record<keyof PersonalityLpm, string> = {
  languageTone: 'Language Tone',
  expressivenessBudget: 'Expressiveness Budget',
  riskTruthfulness: 'Risk Truthfulness',
  autonomyRespect: 'Autonomy Respect',
  replayability: 'Replayability',
  curiosityLimits: 'Curiosity Limits',
}

/**
 * 默认 LPM 取值。
 *
 * 推导依据（设计稿，非实测）：
 *  · §1.3 不变量一「Evidence-First Warmth」——情绪在意但不把感受当事实
 *    → `riskTruthfulness` 取高（0.85）：宁可少承诺也不编造事实；
 *      `languageTone` 取高（0.75）：在意但不夸张（见 §5.3 / §6.1 "显得慢"）。
 *  · §1.3 不变量二「Low-Conflict Growth Path」——可以建议但不裁判
 *    → `autonomyRespect` 取高（0.85）：下一步以选择形式给出，不替用户拍板。
 *  · §1.3 不变量三「Replayable Care」——承诺转成可回放计划
 *    → `replayability` 取高（0.80）：每次承诺都落到可追踪的最小下一步。
 *  · §4.2「好奇不是侵入」
 *    → `curiosityLimits` 取中高（0.60）：会追问，但只在用户已打开的话题内。
 *  · §9.2 Expressiveness Budget「一次对话最多输出多少情绪确认/解释深度」
 *    → `expressivenessBudget` 取中低（0.40）：她"显得慢"、不夸张肯定，
 *      避免把确认变成讨好（对照 §6.1 的克制基调）。
 *
 * 以上数值为设计文档推演值，待实证标定时替换。
 */
export const DEFAULT_AIJADE_LPM: PersonalityLpm = {
  languageTone: 0.75,
  expressivenessBudget: 0.40,
  riskTruthfulness: 0.85,
  autonomyRespect: 0.85,
  replayability: 0.80,
  curiosityLimits: 0.60,
}

function clamp01(v: number): number {
  if (Number.isNaN(v))
    return 0
  return Math.max(0, Math.min(1, v))
}

/**
 * 逐维 clamp 到 [0,1]；缺失维度用 {@link DEFAULT_AIJADE_LPM} 补齐（不凭空发明
 * 新默认值，缺失即回落到设计稿基线）。返回完整六维对象。
 */
export function clampLpm(v: Partial<PersonalityLpm>): PersonalityLpm {
  const out = {} as PersonalityLpm
  for (const dim of PERSONALITY_LPM_DIMS) {
    const raw = v[dim]
    out[dim] = raw === undefined ? DEFAULT_AIJADE_LPM[dim] : clamp01(raw)
  }
  return out
}
