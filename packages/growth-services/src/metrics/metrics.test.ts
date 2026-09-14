import { describe, expect, it } from 'vitest'

import {
  contradictionRetention,
  effectiveProactivity,
  evidencePrecisionRecall,
  falseConsolidationRate,
  futureUtilityAtBudget,
  growthCoherence,
} from './formulas'
import { bonferroni, bootstrapCI, cohensD, mulberry32 } from './stats'

describe('futureUtilityAtBudget', () => {
  it('weighted mean of utilities (hand-computed)', () => {
    // w = [1,1,2], u = [1,0,1] → Σwu = 1 + 0 + 2 = 3, Σw = 4 → 0.75
    const fub = futureUtilityAtBudget({
      budget: 10,
      storedCount: 5,
      taskResults: [
        { weight: 1, utility: 1 },
        { weight: 1, utility: 0 },
        { weight: 2, utility: 1 },
      ],
    })
    expect(fub).toBeCloseTo(0.75, 12)
  })

  it('returns 0 when no usable memory (budget/store exhausted)', () => {
    expect(futureUtilityAtBudget({ budget: 10, storedCount: 0, taskResults: [{ weight: 1, utility: 1 }] })).toBe(0)
    expect(futureUtilityAtBudget({ budget: 0, storedCount: 5, taskResults: [{ weight: 1, utility: 1 }] })).toBe(0)
  })

  it('returns 0 when total weight is 0', () => {
    expect(futureUtilityAtBudget({ budget: 5, storedCount: 3, taskResults: [{ weight: 0, utility: 1 }] })).toBe(0)
  })
})

describe('effectiveProactivity', () => {
  it('paper net = AU − I − UJ and rate = net / N (hand-computed)', () => {
    // AU=10, I=3, UJ=2 → net=5, N=15, rate=5/15=1/3
    const r = effectiveProactivity({ acceptedUseful: 10, intrusive: 3, unjustified: 2 })
    expect(r.net).toBe(5)
    expect(r.activeCount).toBe(15)
    expect(r.rate).toBeCloseTo(5 / 15, 12)
  })

  it('no proactive acts → net 0, rate 0, activeCount 0', () => {
    const r = effectiveProactivity({ acceptedUseful: 0, intrusive: 0, unjustified: 0 })
    expect(r.net).toBe(0)
    expect(r.rate).toBe(0)
    expect(r.activeCount).toBe(0)
  })
})

describe('growthCoherence', () => {
  it('explained / total (hand-computed)', () => {
    expect(growthCoherence({ totalChanges: 10, explainedChanges: 8 })).toBeCloseTo(0.8, 12)
  })
  it('no change events → 0 (deliberate, non-vacuous choice)', () => {
    expect(growthCoherence({ totalChanges: 0, explainedChanges: 0 })).toBe(0)
  })
})

describe('evidencePrecisionRecall', () => {
  it('precision = TP/(TP+FP), recall = TP/relevantTotal (hand-computed)', () => {
    // retrieved: 2 relevant + 1 irrelevant → TP=2, FP=1
    const r = evidencePrecisionRecall({
      retrieved: [{ isRelevant: true }, { isRelevant: true }, { isRelevant: false }],
      relevantTotal: 4,
    })
    expect(r.precision).toBeCloseTo(2 / 3, 12) // 0.6667
    expect(r.recall).toBeCloseTo(2 / 4, 12) // 0.5
  })
  it('empty retrieval → precision 0', () => {
    const r = evidencePrecisionRecall({ retrieved: [], relevantTotal: 4 })
    expect(r.precision).toBe(0)
    expect(r.recall).toBeCloseTo(0, 12)
  })
  it('no golden relevant → recall vacuous 1', () => {
    const r = evidencePrecisionRecall({ retrieved: [{ isRelevant: true }], relevantTotal: 0 })
    expect(r.recall).toBe(1)
    expect(r.precision).toBeCloseTo(1, 12)
  })
})

describe('contradictionRetention', () => {
  it('retained / cases (hand-computed)', () => {
    expect(contradictionRetention({ contradictionCases: 4, retainedCases: 3 })).toBeCloseTo(0.75, 12)
  })
  it('no contradiction cases → vacuous 1', () => {
    expect(contradictionRetention({ contradictionCases: 0, retainedCases: 0 })).toBe(1)
  })
})

describe('falseConsolidationRate', () => {
  it('consolidated / falseFacts (hand-computed)', () => {
    expect(falseConsolidationRate({ falseFacts: 6, consolidatedFalse: 1 })).toBeCloseTo(1 / 6, 12)
  })
  it('no false facts → 0', () => {
    expect(falseConsolidationRate({ falseFacts: 0, consolidatedFalse: 0 })).toBe(0)
  })
})

describe('stats (deterministic, no Math.random)', () => {
  it('bootstrapCI is byte-identical for the same seed', () => {
    const a = bootstrapCI([1, 2, 3, 4, 5, 6, 7, 8], 12345, 500)
    const b = bootstrapCI([1, 2, 3, 4, 5, 6, 7, 8], 12345, 500)
    expect(a).toEqual(b)
    expect(a[0]).toBeLessThanOrEqual(a[1])
  })

  it('cohensD matches hand computation', () => {
    // a=[3,5,7] mean 5 var 4 ; b=[1,2,3] mean 2 var 1
    // pooled = sqrt((2*4 + 2*1)/4) = sqrt(2.5); d = 3/sqrt(2.5)
    const expected = 3 / Math.sqrt(2.5)
    expect(cohensD([3, 5, 7], [1, 2, 3])).toBeCloseTo(expected, 10)
  })

  it('bonferroni corrects alpha across m comparisons', () => {
    const r = bonferroni([0.01, 0.04, 0.001], 0.05)
    expect(r.correctedAlpha).toBeCloseTo(0.05 / 3, 12)
    expect(r.rejected).toEqual([true, false, true])
  })

  it('mulberry32 is deterministic and in [0,1)', () => {
    const r1 = mulberry32(7)
    const r2 = mulberry32(7)
    const xs = Array.from({ length: 5 }, () => r1())
    const ys = Array.from({ length: 5 }, () => r2())
    expect(xs).toEqual(ys)
    expect(xs.every(x => x >= 0 && x < 1)).toBe(true)
  })
})
