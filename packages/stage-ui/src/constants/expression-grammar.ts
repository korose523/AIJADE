/**
 * expression-grammar — AIJADE 表情线索语法（声明式、渲染器无关）。
 *
 * 设计稿产物：本节内容提炼自《AIJADE v9 角色背景设计文档（角色圣经）》§3.2。
 * 圣经要求表情是**固定规则**而非随机抖动——因此这里只声明"什么信号触发什么
 * 线索、停留多久、用哪种语义通道"，任何 VRM / Live2D / MMD 专有参数名都**不**
 * 出现在此文件中；per-format 的映射留给各渲染器自行实现。
 *
 * 本文件是纯数据 + 纯函数，可被单元测试，亦不依赖任何运行时状态。
 */

import type { PerformanceEmotion } from '@proj-aijade/memory-pgvector/performance'

/** 四条内置表情线索的标识。 */
export type ExpressionCueId
  = | 'confirm_smile'
    | 'gaze_down'
    | 'measure_blink'
    | 'head_tilt'

/**
 * 单条表情线索。
 * `channels` 是**语义层**通道（情绪/视线/头部微倾/眨眼节律/呼吸节律），渲染器
 * 负责把它们映射成具体格式的表情权重或骨骼姿态。
 */
export interface ExpressionCue {
  id: ExpressionCueId
  /** 人类可读名（英文，设计稿）。 */
  label: string
  /** 触发条件（对应 §3.2 的判定规则，自然语言描述）。 */
  trigger: string
  channels: {
    /** 语义情绪通道；落到具体表情由渲染器映射。 */
    emotion?: PerformanceEmotion
    /** 视线方向。 */
    gaze?: 'center' | 'up' | 'down' | 'left' | 'right'
    /** 头部侧倾（度，正值右倾）。非零即"歪头"。 */
    headRoll?: number
    /** 眨眼节律倍率（<1 更慢/更稳，>1 更快）。 */
    blinkRateScale?: number
    /** 呼吸周期（毫秒）；值越大呼吸越稳、越慢。 */
    breathPeriodMs?: number
  }
  /** 停留时长区间 [min, max]（毫秒），由渲染器在区间内取确定值。 */
  dwellMs: readonly [number, number]
  /** 为何这样设计（设计稿依据）。 */
  rationale: string
}

/**
 * AIJADE 表情语法表，严格对应 §3.2 的四条规则，声明顺序即 `resolveExpressionCues`
 * 的返回顺序。
 */
export const AIJADE_EXPRESSION_GRAMMAR: readonly ExpressionCue[] = [
  {
    id: 'confirm_smile',
    label: 'Confirm Smile',
    trigger: '用户给出可验证的行动或反馈（做了某事 / 带来了结果 / 引用了事实）。',
    channels: {
      emotion: 'grateful',
    },
    dwellMs: [300, 700],
    rationale:
      '圣经原文写"短暂停顿 0.3–0.7s"。选 `grateful` 而非 `happy`：她确认的是"你做到了"'
      + '这一**事实信号**，不是对用户的讨好。`grateful` 在 PerformanceEmotion 语义里'
      + '指向"被印证/被托付"的克制感激，强度上限低于 `happy`（见 avatar-expression 的'
      + ' EMOTION_INTENSITY），因此天然不会变成夸张肯定——与 §6.1 "不夸张肯定"一致。',
  },
  {
    id: 'gaze_down',
    label: 'Gaze Down',
    trigger: '出现"情绪 / 事实混合输入"或理解歧义（需要先分清再回应）。',
    channels: {
      gaze: 'down',
    },
    dwellMs: [200, 500],
    rationale:
      '视线下移表示"我在把情绪层和事实层分开，而不是急着接话"。短促停留，'
      + '对应 §3.2 的"先复述信号并做情绪/事实分层"前奏。',
  },
  {
    id: 'measure_blink',
    label: 'Measure Blink',
    trigger: '进入解释 / 计划阶段（开始给最小可执行下一步）。',
    channels: {
      blinkRateScale: 0.8,
      breathPeriodMs: 4200,
    },
    dwellMs: [400, 800],
    rationale:
      '解释阶段需要稳定、不慌张。`blinkRateScale < 1` 让眨眼间隔略增（更沉稳），'
      + '`breathPeriodMs` 变长（4200ms，慢于静息基线）让呼吸更稳——传递"我在认真量度"'
      + '而非随机发呆。',
  },
  {
    id: 'head_tilt',
    label: 'Head Tilt',
    trigger: '用户提供非单调 / 反常 / 矛盾信息（与已有信号不一致）。',
    channels: {
      headRoll: 8,
    },
    dwellMs: [300, 600],
    rationale:
      '头侧倾（非零 `headRoll`）是"我注意到了不一致，正在重新对齐"的非语言信号。'
      + '它不表示赞同也不表示反对，只表示"这条信息被认真对待了"。',
  },
]

/** 按 id 查找单条线索；未命中返回 undefined。 */
export function findExpressionCue(id: ExpressionCueId): ExpressionCue | undefined {
  return AIJADE_EXPRESSION_GRAMMAR.find(c => c.id === id)
}

/** 触发信号（由上游对话理解模块判定，纯布尔）。 */
export interface ExpressionSignals {
  /** 用户给出可验证的行动或反馈。 */
  hasVerifiableFeedback: boolean
  /** 出现情绪 / 事实混合输入或理解歧义。 */
  mixedEmotionAndFact: boolean
  /** 进入解释 / 计划阶段。 */
  isExplaining: boolean
  /** 用户提供非单调 / 反常 / 矛盾信息。 */
  isNonMonotonic: boolean
}

/**
 * 纯函数、确定性：根据信号返回命中的线索，按 `AIJADE_EXPRESSION_GRAMMAR`
 * 声明顺序。无副作用、无随机性，便于测试与回放。
 */
export function resolveExpressionCues(signals: ExpressionSignals): ExpressionCue[] {
  return AIJADE_EXPRESSION_GRAMMAR.filter((cue) => {
    switch (cue.id) {
      case 'confirm_smile':
        return signals.hasVerifiableFeedback
      case 'gaze_down':
        return signals.mixedEmotionAndFact
      case 'measure_blink':
        return signals.isExplaining
      case 'head_tilt':
        return signals.isNonMonotonic
      default:
        return false
    }
  })
}
