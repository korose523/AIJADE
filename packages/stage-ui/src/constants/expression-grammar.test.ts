import { describe, expect, it } from 'vitest'

import {
  AIJADE_EXPRESSION_GRAMMAR,
  findExpressionCue,
  resolveExpressionCues,
  type ExpressionCueId,
} from './expression-grammar'

describe('expression-grammar', () => {
  it('findExpressionCue 命中四条已知 id', () => {
    expect(findExpressionCue('confirm_smile')?.id).toBe('confirm_smile')
    expect(findExpressionCue('gaze_down')?.id).toBe('gaze_down')
    expect(findExpressionCue('measure_blink')?.id).toBe('measure_blink')
    expect(findExpressionCue('head_tilt')?.id).toBe('head_tilt')
  })

  it('findExpressionCue 未命中返回 undefined', () => {
    expect(findExpressionCue('not_a_cue' as ExpressionCueId)).toBeUndefined()
  })

  it('confirm_smile.dwellMs 严格等于 [300, 700]（圣经原文 0.3–0.7s）', () => {
    const cue = findExpressionCue('confirm_smile')
    expect(cue).toBeDefined()
    expect(cue!.dwellMs).toEqual([300, 700])
  })

  it('AIJADE_EXPRESSION_GRAMMAR 恰好四条且 id 唯一、顺序固定', () => {
    expect(AIJADE_EXPRESSION_GRAMMAR).toHaveLength(4)
    const ids = AIJADE_EXPRESSION_GRAMMAR.map(c => c.id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(ids).toEqual(['confirm_smile', 'gaze_down', 'measure_blink', 'head_tilt'])
  })

  it('resolveExpressionCues 无信号时返回空数组', () => {
    const cues = resolveExpressionCues({
      hasVerifiableFeedback: false,
      mixedEmotionAndFact: false,
      isExplaining: false,
      isNonMonotonic: false,
    })
    expect(cues).toEqual([])
  })

  it('resolveExpressionCues 全信号时按声明顺序返回四条', () => {
    const cues = resolveExpressionCues({
      hasVerifiableFeedback: true,
      mixedEmotionAndFact: true,
      isExplaining: true,
      isNonMonotonic: true,
    })
    expect(cues.map(c => c.id)).toEqual([
      'confirm_smile',
      'gaze_down',
      'measure_blink',
      'head_tilt',
    ])
  })

  it('resolveExpressionCues 部分信号时只返回命中的、保序', () => {
    const cues = resolveExpressionCues({
      hasVerifiableFeedback: false,
      mixedEmotionAndFact: true,
      isExplaining: false,
      isNonMonotonic: true,
    })
    expect(cues.map(c => c.id)).toEqual(['gaze_down', 'head_tilt'])
  })

  it('resolveExpressionCues 是纯函数、确定性（同输入同输出）', () => {
    const signals = {
      hasVerifiableFeedback: true,
      mixedEmotionAndFact: false,
      isExplaining: true,
      isNonMonotonic: false,
    }
    const a = resolveExpressionCues(signals)
    const b = resolveExpressionCues(signals)
    expect(a).toEqual(b)
    expect(a.map(c => c.id)).toEqual(['confirm_smile', 'measure_blink'])
  })
})
