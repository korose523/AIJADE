import { describe, expect, it } from 'vitest'

import { auc, predictSalience, SALIENCE_WEIGHTS } from './salience'

describe('predicted salience — v4 §7.2, no gold labels', () => {
  it('every component and the total stay inside [0,1]', () => {
    const samples = [
      '',
      'ok',
      'haha',
      'I will visit my sister in Busan on March 3rd next year.',
      'My favorite band is Radiohead and I have seen them twice in Seoul.',
      'Lorem ipsum dolor sit amet '.repeat(50),
      'Did you ever go to Jeju Island?',
    ]
    for (const s of samples) {
      const b = predictSalience(s, [])
      for (const [k, v] of Object.entries(b)) {
        expect(v, `${k} for "${s.slice(0, 20)}"`).toBeGreaterThanOrEqual(0)
        expect(v, `${k} for "${s.slice(0, 20)}"`).toBeLessThanOrEqual(1)
      }
    }
  })

  it('weights sum to 1 — otherwise `total` is not a bounded score', () => {
    const sum = Object.values(SALIENCE_WEIGHTS).reduce((a, b) => a + b, 0)
    expect(sum).toBeCloseTo(1, 10)
  })

  it('ranks a commitment above filler chatter', () => {
    const filler = predictSalience('haha yeah ok', [])
    const commitment = predictSalience('I will move to Seoul next March.', [])
    expect(commitment.commitment).toBe(1)
    expect(filler.commitment).toBe(0)
    expect(commitment.total).toBeGreaterThan(filler.total)
  })

  it('judges repeated content as less novel than fresh content', () => {
    const repeated = 'we went to the same cafe again today'
    const priors = ['we went to the same cafe again yesterday', 'the same cafe again']
    const fresh = 'my brother just adopted a three legged dog named Pixel'
    expect(predictSalience(repeated, priors).novelty)
      .toBeLessThan(predictSalience(fresh, priors).novelty)
  })

  it('is deterministic — the same input always yields the same score', () => {
    const a = predictSalience('I plan to finish the paper by Friday.', ['hello there'])
    const b = predictSalience('I plan to finish the paper by Friday.', ['hello there'])
    expect(a).toEqual(b)
  })

  it('reads no label: the score depends only on content and priors', () => {
    // 同一句话在不同前文下分数不同 ⇒ 确实在用上下文；与任何金标准无关
    const withPrior = predictSalience('yes, exactly the same', ['yes, exactly the same'])
    const withoutPrior = predictSalience('yes, exactly the same', [])
    expect(withPrior.total).not.toBe(withoutPrior.total)
  })
})

describe('auc', () => {
  it('is 1 under perfect separation and 0.5 under chance', () => {
    expect(auc([3, 2, 1, 0], [1, 1, 0, 0])).toBe(1)
    // 正负完全交叉：pos={2,3} vs neg={1,4} ⇒ 2 胜 2 负
    expect(auc([1, 2, 3, 4], [0, 1, 1, 0])).toBe(0.5)
  })

  it('counts ties as half a win', () => {
    expect(auc([1, 1], [1, 0])).toBe(0.5)
  })

  it('returns 0.5 when one class is empty — never a fake score', () => {
    expect(auc([1, 2, 3], [0, 0, 0])).toBe(0.5)
    expect(auc([1, 2, 3], [1, 1, 1])).toBe(0.5)
  })

  it('is the mirror of itself: swapping labels mirrors the value', () => {
    expect(auc([3, 2, 1, 0], [0, 0, 1, 1])).toBe(0)
  })
})
