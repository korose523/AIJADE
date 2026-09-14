import { describe, expect, it } from 'vitest'

import {
  bcaBootstrapCI,
  bootstrapCI,
  bootstrapPooledPrecision,
  chiSquare2x2,
  cohensH,
  cramersV,
  differenceInDifferences,
  erf,
  holmBonferroni,
  logOddsInteraction,
  mcnemarExactOrChi,
  minDetectableEffectProportion,
  mulberry32,
  normalCdf,
  normalSf,
  oddsRatio,
  pooledDifferenceInDifferences,
  powerForEffectProportion,
  riskDifference,
  riskDifferenceCI,
  twoSidedNormalP,
} from './stats'

describe('mulberry32', () => {
  it('is deterministic for a given seed', () => {
    const a = mulberry32(123)
    const b = mulberry32(123)
    for (let i = 0; i < 20; i++)
      expect(a()).toBe(b())
  })
  it('produces values in [0,1)', () => {
    const r = mulberry32(7)
    for (let i = 0; i < 1000; i++) {
      const v = r()
      expect(v).toBeGreaterThanOrEqual(0)
      expect(v).toBeLessThan(1)
    }
  })
})

describe('erf / normalCdf', () => {
  it('erf(0) = 0, normalCdf(0) = 0.5', () => {
    expect(erf(0)).toBeCloseTo(0, 6)
    expect(normalCdf(0)).toBeCloseTo(0.5, 6)
  })
  it('normalCdf(1.959964) ≈ 0.975', () => {
    expect(normalCdf(1.959964)).toBeCloseTo(0.975, 3)
  })
  it('normalCdf is symmetric', () => {
    expect(normalCdf(-1.96)).toBeCloseTo(1 - normalCdf(1.96), 4)
  })
})

describe('bootstrapCI', () => {
  it('recovers the mean of a known sample', () => {
    const xs = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    const ci = bootstrapCI(xs, { seed: 1 })
    expect(ci.mean).toBeCloseTo(5.5, 6)
    // CI should bracket the mean and be narrower than the full range.
    expect(ci.lo).toBeLessThan(5.5)
    expect(ci.hi).toBeGreaterThan(5.5)
    expect(ci.hi - ci.lo).toBeLessThan(5)
  })
  it('is reproducible for a fixed seed', () => {
    const xs = Array.from({ length: 200 }, (_, i) => (i % 3) + 1)
    const a = bootstrapCI(xs, { seed: 99 })
    const b = bootstrapCI(xs, { seed: 99 })
    expect(a.lo).toBe(b.lo)
    expect(a.hi).toBe(b.hi)
  })
  it('returns NaN for an empty sample', () => {
    const ci = bootstrapCI([], { seed: 1 })
    expect(Number.isNaN(ci.mean)).toBe(true)
  })
})

describe('chiSquare2x2', () => {
  it('no association -> statistic 0, p = 1', () => {
    const r = chiSquare2x2(25, 25, 25, 25)
    expect(r.statistic).toBeCloseTo(0, 6)
    expect(r.p).toBeCloseTo(1, 6)
  })
  it('perfect association -> very small p', () => {
    const r = chiSquare2x2(50, 0, 0, 50)
    expect(r.statistic).toBeGreaterThan(40)
    expect(r.p).toBeLessThan(1e-6)
  })
  it('matches the hand-computed 2x2 [[30,10],[10,30]]', () => {
    // row0=40, row1=40, col0=40, col1=40, n=80, cross=30*30-10*10=800
    // stat = 80*800^2 / (40*40*40*40) = 80*640000 / 2560000 = 20
    const r = chiSquare2x2(30, 10, 10, 30, false)
    expect(r.statistic).toBeCloseTo(20, 4)
    // p = 2*(1-Phi(sqrt(20))) = 2*(1-Phi(4.472)) ≈ 2*(1-0.9999962) ≈ 7.6e-6
    expect(r.p).toBeLessThan(1e-4)
    expect(r.p).toBeGreaterThan(0)
  })
})

describe('differenceInDifferences', () => {
  it('recovers a known additive interaction', () => {
    // Build per-unit values so cell means are exactly A=0, B=1, C=1, D=3.
    // DiD = D - C - B + A = 3 - 1 - 1 + 0 = 1.
    const A = [0, 0, 0, 0]
    const B = [1, 1, 1, 1]
    const C = [1, 1, 1, 1]
    const D = [3, 3, 3, 3]
    const r = differenceInDifferences(A, B, C, D, { seed: 5 })
    expect(r.estimate).toBeCloseTo(1, 6)
    expect(r.ci.lo).toBeCloseTo(1, 6)
    expect(r.ci.hi).toBeCloseTo(1, 6)
  })
  it('is reproducible', () => {
    const mk = () => [0.1, 0.4, 0.2, 0.5, 0.3, 0.6]
    const a = differenceInDifferences(mk(), mk(), mk(), mk(), { seed: 42 })
    const b = differenceInDifferences(mk(), mk(), mk(), mk(), { seed: 42 })
    expect(a.estimate).toBe(b.estimate)
    expect(a.ci.lo).toBe(b.ci.lo)
  })
})

describe('effect sizes (hand-computed 2x2 [[30,10],[10,30]])', () => {
  // OR = 30*30/(10*10) = 9 ; RD = 0.75 - 0.25 = 0.5
  it('oddsRatio = 9, riskDifference = 0.5', () => {
    expect(oddsRatio(30, 10, 10, 30)).toBeCloseTo(9, 6)
    expect(riskDifference(30, 10, 10, 30)).toBeCloseTo(0.5, 6)
  })
  it('cramersV from chi-square 20, n 80 = 0.5', () => {
    expect(cramersV(20, 80)).toBeCloseTo(0.5, 6)
  })
  it('cohensH(0.75, 0.25) = 2*asin(sqrt(.75)) - 2*asin(sqrt(.25)) ≈ 1.0472', () => {
    expect(cohensH(0.75, 0.25)).toBeCloseTo(1.0472, 4)
  })
  it('logOddsInteraction = log(9) ≈ 2.1972, se ≈ 0.5164', () => {
    const r = logOddsInteraction(30, 10, 10, 30)
    expect(r.estimate).toBeCloseTo(Math.log(9), 6)
    expect(r.se).toBeCloseTo(Math.sqrt(1 / 30 + 1 / 10 + 1 / 10 + 1 / 30), 6)
    expect(r.p).toBeLessThan(0.001)
  })
  it('0.5 correction keeps the OR finite when a cell is empty', () => {
    // [[0,10],[10,30]] would divide by zero without correction.
    expect(Number.isFinite(oddsRatio(0, 10, 10, 30))).toBe(true)
    expect(Number.isFinite(logOddsInteraction(0, 10, 10, 30).estimate)).toBe(true)
  })
})

describe('holmBonferroni', () => {
  it('rejects all three when all raw p <= alpha/(m-k)', () => {
    const r = holmBonferroni([0.01, 0.04, 0.06], 0.05, ['a', 'b', 'c'])
    // sorted [0.01,0.04,0.06]: adj = [0.03, 0.08, 0.06] -> monotone [0.03,0.08,0.08]
    expect(r.map(s => s.reject)).toEqual([true, false, false])
    expect(r[0].adjustedP).toBeCloseTo(0.03, 6)
    expect(r[1].adjustedP).toBeCloseTo(0.08, 6)
    expect(r[2].adjustedP).toBeCloseTo(0.08, 6)
  })
  it('adjusts monotonically (in sorted order) and never exceeds 1', () => {
    const r = holmBonferroni([0.2, 0.1, 0.05, 0.5], 0.05)
    const sorted = [...r].sort((x, y) => x.p - y.p)
    for (let i = 1; i < sorted.length; i++)
      expect(sorted[i].adjustedP).toBeGreaterThanOrEqual(sorted[i - 1].adjustedP)
    expect(r.every(s => s.adjustedP <= 1)).toBe(true)
  })
})

describe('mcnemarExactOrChi', () => {
  it('uses exact binomial when discordant < 25', () => {
    // b=5, c=0 -> discordant=5, two-sided = P(X<=0)+P(X>=5) = 2/32 = 0.0625
    const r = mcnemarExactOrChi(10, 5, 0, 10)
    expect(r.usedExact).toBe(true)
    expect(r.pExact).toBeCloseTo(0.0625, 6)
    expect(r.p).toBeCloseTo(0.0625, 6)
  })
  it('uses chi-square form when discordant >= 25', () => {
    const r = mcnemarExactOrChi(10, 30, 8, 200)
    expect(r.usedExact).toBe(false)
    expect(r.chiSquare).toBeCloseTo((Math.abs(30 - 8) - 1) ** 2 / 38, 6)
    expect(r.p).toBe(r.pChiSquare)
    expect(r.p).toBeLessThan(0.01)
  })
  it('returns p=1 when there is no discordance', () => {
    const r = mcnemarExactOrChi(5, 0, 0, 20)
    expect(r.p).toBe(1)
    expect(r.usedExact).toBe(false)
  })
})

describe('pooled-precision bootstrap + DiD (public, reused by harness)', () => {
  it('bootstrapPooledPrecision recovers the pooled precision', () => {
    const skills = [{ succ: 0, calls: 1 }, { succ: 1, calls: 1 }]
    const ci = bootstrapPooledPrecision(skills, { seed: 1 })
    expect(ci.mean).toBeCloseTo(0.5, 6)
    expect(ci.lo).toBeLessThanOrEqual(ci.mean)
    expect(ci.hi).toBeGreaterThanOrEqual(ci.mean)
  })
  it('pooledDifferenceInDifferences = 1 for D-success vs others-fail', () => {
    const A = [{ succ: 0, calls: 1 }]
    const B = [{ succ: 0, calls: 1 }]
    const C = [{ succ: 0, calls: 1 }]
    const D = [{ succ: 1, calls: 1 }]
    const r = pooledDifferenceInDifferences(A, B, C, D, { seed: 3 })
    expect(r.estimate).toBeCloseTo(1, 6)
  })
})

describe('bcaBootstrapCI', () => {
  it('is reproducible and brackets the mean', () => {
    const xs = Array.from({ length: 200 }, (_, i) => (i % 3) + 1)
    const a = bcaBootstrapCI(xs, { seed: 7 })
    const b = bcaBootstrapCI(xs, { seed: 7 })
    expect(a.lo).toBe(b.lo)
    expect(a.hi).toBe(b.hi)
    expect(a.lo).toBeLessThanOrEqual(a.mean)
    expect(a.hi).toBeGreaterThanOrEqual(a.mean)
  })
  it('returns NaN when n < 2', () => {
    const ci = bcaBootstrapCI([1], { seed: 1 })
    expect(Number.isNaN(ci.mean)).toBe(true)
  })
})

describe('minDetectableEffectProportion', () => {
  it('matches the review table (≈10.4pp at 360/cell, ≈12.8pp at 240/cell)', () => {
    // Exact two-proportion solve; within 0.5pp of the review's approximate table.
    expect(minDetectableEffectProportion(360) * 100).toBeCloseTo(10.4, 0)
    expect(minDetectableEffectProportion(240) * 100).toBeCloseTo(12.8, 0)
  })
})

describe('powerForEffectProportion (derived, not hand-typed)', () => {
  it('is monotonic in n and bounded in [0,1]', () => {
    const small = powerForEffectProportion(0.10, 120)
    const med = powerForEffectProportion(0.10, 240)
    const large = powerForEffectProportion(0.10, 360)
    expect(med).toBeGreaterThan(small)
    expect(large).toBeGreaterThan(med)
    for (const p of [small, med, large])
      expect(p).toBeGreaterThanOrEqual(0)
    expect(large).toBeLessThanOrEqual(1)
  })
  it('a 10pp effect at 240/cell has modest power; a 5pp effect is underpowered', () => {
    // Qualitative check only (the review's exact 0.56/0.74 figures are NOT
    // trusted — see the project's history of wrong hand-typed reference values).
    const p10 = powerForEffectProportion(0.10, 240)
    const p5 = powerForEffectProportion(0.05, 240)
    expect(p10).toBeGreaterThan(0.5)
    expect(p10).toBeLessThan(0.7)
    expect(p5).toBeLessThan(0.24) // design can only resolve ~>=10pp effects
  })
  it('returns NaN for degenerate inputs', () => {
    expect(Number.isNaN(powerForEffectProportion(0.10, 0))).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// Tail accuracy + degenerate-input robustness (added with the stats hardening)
// ---------------------------------------------------------------------------

describe('normalSf — tail-accurate survival function', () => {
  // Tabulated reference values, asserted to 1e-12 relative.
  const TABULATED: [number, number][] = [
    [0, 0.5],
    [1, 0.15865525393145705],
    [1.959963984540054, 0.025],
    [2.5758293035489004, 0.005],
    [3, 0.0013498980316300933],
    [4, 3.167124183311987e-05],
    [5, 2.866515718791939e-07],
    [6, 9.865876450376946e-10],
    [7, 1.2798125438858341e-12],
    [8, 6.220960574271786e-16],
    [10, 7.619853024160526e-24],
  ]

  it('matches the tabulated values to 1e-12 relative', () => {
    for (const [z, expected] of TABULATED)
      expect(Math.abs(normalSf(z) - expected) / expected).toBeLessThan(1e-12)
  })

  it('stays accurate in the far tail where `1 - normalCdf` underflows to 0', () => {
    // The whole point of this function: the old expression returned exactly 0
    // for chi-square >= ~90, losing the magnitude of the evidence entirely.
    expect(normalSf(10)).toBeGreaterThan(0)
    expect(normalSf(10)).toBeCloseTo(7.61985302416e-24, 35)
    expect(2 * (1 - normalCdf(10))).toBe(0) // documents the old behaviour
    expect(normalSf(20)).toBeGreaterThan(0)
    expect(normalSf(20)).toBeCloseTo(2.7536241186062337e-89, 100)
  })

  it('is symmetric: sf(-x) = 1 - sf(x)', () => {
    for (const x of [0.3, 1, 1.5, 2, 2.5, 4]) {
      expect(Math.abs(normalSf(-x) - (1 - normalSf(x)))).toBeLessThan(1e-15)
    }
  })

  it('is non-increasing and bounded in [0, 1]; strictly decreasing where not saturated', () => {
    // Below sf ≈ 1e-16 the upper tail saturates: 1 - 3e-20 rounds to exactly 1,
    // so sf(-40) = sf(-30) = 1. Non-increasing is the honest invariant there.
    let prev = normalSf(-40)
    for (let z = -39.75; z <= 40; z += 0.25) {
      const cur = normalSf(z)
      expect(cur).toBeGreaterThanOrEqual(0)
      expect(cur).toBeLessThanOrEqual(1)
      expect(cur).toBeLessThanOrEqual(prev)
      prev = cur
    }
    // Over the range that matters for inference it must be strictly decreasing.
    // It saturates to exactly 1 below z ≈ -8.3 (where sf(|z|) < eps/2) and to
    // exactly 0 above z ≈ 38.6 (where φ underflows), so the range is bounded.
    prev = normalSf(-8)
    for (let z = -7.75; z <= 36; z += 0.25) {
      const cur = normalSf(z)
      expect(cur).toBeLessThan(prev)
      prev = cur
    }
  })

  it('handles the infinities and NaN', () => {
    expect(normalSf(Number.POSITIVE_INFINITY)).toBe(0)
    expect(normalSf(Number.NEGATIVE_INFINITY)).toBe(1)
    expect(Number.isNaN(normalSf(Number.NaN))).toBe(true)
  })

  it('twoSidedNormalP is the two-sided tail of |z|', () => {
    expect(twoSidedNormalP(1.959963984540054)).toBeCloseTo(0.05, 10)
    expect(twoSidedNormalP(-2.5758293035489004)).toBeCloseTo(0.01, 10)
    expect(twoSidedNormalP(0)).toBeCloseTo(1, 12)
  })
})

describe('chiSquare2x2 — degenerate margins', () => {
  // Regression: a zero margin made `denom` 0, so stat became 0/0 = NaN and the
  // NaN then poisoned every Holm-adjusted p-value in the same family.
  it('returns p = 1 (not NaN) when a margin is empty', () => {
    for (const table of [[5, 0, 3, 0], [2, 2, 0, 0], [0, 5, 0, 3], [0, 0, 0, 0]] as const) {
      const r = chiSquare2x2(table[0], table[1], table[2], table[3])
      expect(Number.isNaN(r.p)).toBe(false)
      expect(r.p).toBe(1)
      expect(r.statistic).toBe(0)
    }
  })

  it('still detects association when no margin is empty', () => {
    // Yates-corrected: cross = 2500, adj = 2450, stat = 100*2450^2/50^4 = 96.04
    const r = chiSquare2x2(50, 0, 0, 50)
    expect(r.statistic).toBeCloseTo(96.04, 2)
    expect(r.p).toBeLessThan(1e-20)
    expect(r.p).toBeGreaterThan(0)
  })

  it('reports far-tail p instead of underflowing to 0', () => {
    // [[86,14],[14,86]] -> n=200, cross=7200, stat = 200*7200^2/100^4 = 103.68
    // The old `2*(1-normalCdf(sqrt(103.68)))` returned exactly 0.
    const r = chiSquare2x2(86, 14, 14, 86, false)
    expect(r.statistic).toBeCloseTo(103.68, 2)
    expect(r.p).toBeGreaterThan(0)
    expect(r.p).toBeLessThan(1e-20)
  })
})

describe('holmBonferroni — non-finite p-values', () => {
  it('does not let one NaN inflate the correction for the others', () => {
    // Family [0.01, NaN, 0.04]: the two testable hypotheses must be corrected
    // against m = 2, not m = 3.
    const r = holmBonferroni([0.01, Number.NaN, 0.04], 0.05, ['a', 'b', 'c'])
    expect(r[0].adjustedP).toBeCloseTo(0.02, 10)
    expect(r[2].adjustedP).toBeCloseTo(0.04, 10)
    expect(r[0].reject).toBe(true)
    expect(r[2].reject).toBe(true)
    // The untestable entry is reported, not silently dropped.
    expect(Number.isNaN(r[1].adjustedP)).toBe(true)
    expect(r[1].reject).toBe(false)
  })

  it('treats Infinity as untestable too', () => {
    const r = holmBonferroni([0.01, Number.POSITIVE_INFINITY], 0.05)
    expect(r[0].adjustedP).toBeCloseTo(0.01, 10)
    expect(Number.isNaN(r[1].adjustedP)).toBe(true)
  })

  it('is unchanged when every p-value is finite', () => {
    const r = holmBonferroni([0.01, 0.04, 0.06], 0.05, ['a', 'b', 'c'])
    expect(r.map(s => s.reject)).toEqual([true, false, false])
    expect(r[0].adjustedP).toBeCloseTo(0.03, 10)
    expect(r[1].adjustedP).toBeCloseTo(0.08, 10)
  })
})

describe('bcaBootstrapCI — degenerate distributions', () => {
  it('returns a finite interval when every resample equals the statistic', () => {
    // All values identical -> every bootstrap mean equals the original, so the
    // bias-correction rank fraction lands exactly on 1. Before the clamp,
    // normalQuantile(1) = Infinity turned every bound into NaN.
    const ci = bcaBootstrapCI([5, 5, 5, 5], { seed: 1 })
    expect(Number.isFinite(ci.lo)).toBe(true)
    expect(Number.isFinite(ci.hi)).toBe(true)
    expect(ci.mean).toBe(5)
    expect(ci.lo).toBe(5)
    expect(ci.hi).toBe(5)
  })

  it('returns a finite interval for a two-point sample that saturates the rank', () => {
    const ci = bcaBootstrapCI([0, 1], { seed: 2 })
    expect(Number.isFinite(ci.lo)).toBe(true)
    expect(Number.isFinite(ci.hi)).toBe(true)
    expect(ci.mean).toBeCloseTo(0.5, 12)
    expect(ci.lo).toBeLessThanOrEqual(0.5)
    expect(ci.hi).toBeGreaterThanOrEqual(0.5)
  })
})

describe('bootstrap distributions — non-finite draws are discarded', () => {
  it('bootstrapPooledPrecision returns NaN bounds when every draw is undefined', () => {
    // calls = 0 everywhere -> the pooled precision is undefined; the interval
    // must be NaN rather than a corrupted percentile of a NaN-laden array.
    const ci = bootstrapPooledPrecision([{ succ: 0, calls: 0 }], { seed: 1 })
    expect(Number.isNaN(ci.mean)).toBe(true)
    expect(Number.isNaN(ci.lo)).toBe(true)
    expect(Number.isNaN(ci.hi)).toBe(true)
  })
})

describe('riskDifferenceCI — Newcombe hybrid score', () => {
  it('brackets the point estimate and excludes 0 for the hand-computed table', () => {
    // [[30,10],[10,30]]: p1 = 0.75, p2 = 0.25, RD = 0.5
    const ci = riskDifferenceCI(30, 10, 10, 30)
    expect(ci.estimate).toBeCloseTo(0.5, 12)
    expect(ci.lo).toBeLessThan(0.5)
    expect(ci.hi).toBeGreaterThan(0.5)
    expect(ci.lo).toBeGreaterThan(0)
  })

  it('keeps a non-degenerate interval at the boundary p1 = 1, p2 = 0', () => {
    // A Wald interval would collapse to zero width here.
    const ci = riskDifferenceCI(10, 0, 0, 10)
    expect(ci.estimate).toBe(1)
    expect(ci.lo).toBeLessThan(1)
    expect(ci.lo).toBeGreaterThan(0)
    expect(ci.hi).toBeLessThanOrEqual(1)
  })

  it('returns NaN when a margin is empty', () => {
    const ci = riskDifferenceCI(0, 0, 5, 5)
    expect(Number.isNaN(ci.estimate)).toBe(true)
    expect(Number.isNaN(ci.lo)).toBe(true)
  })

  it('narrows as n grows', () => {
    const small = riskDifferenceCI(15, 5, 5, 15)
    const large = riskDifferenceCI(150, 50, 50, 150)
    expect(large.hi - large.lo).toBeLessThan(small.hi - small.lo)
  })
})
