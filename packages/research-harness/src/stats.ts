/**
 * Statistics for the RQ-C 2x2 harness.
 *
 * Everything here is dependency-free (no new npm packages). Bootstrap CIs use a
 * seeded PRNG so results are reproducible; the chi-square p-value is computed
 * from an error-function approximation of the normal CDF.
 *
 * ## Purity contract
 *
 * Every function in this module is a **pure function**: no global state, no
 * `Date.now()`, no `Math.random()`. Randomness enters only through an explicit
 * `seed` argument (seeded `mulberry32`). This is what makes the whole RQ-C
 * pipeline reproducible.
 */

/** mulberry32: small, fast, seedable PRNG. Same seed -> same sequence. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return function () {
    a = (a + 0x6D2B79F5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** Linear-interpolated percentile of an already-sorted array. */
function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0)
    return Number.NaN
  const idx = (sorted.length - 1) * p
  const lo = Math.floor(idx)
  const hi = Math.ceil(idx)
  if (lo === hi)
    return sorted[lo]
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo)
}

/**
 * Build a 95% percentile CI from a bootstrap distribution.
 *
 * Non-finite draws are discarded first. A resample can legitimately be
 * undefined — e.g. a pooled-precision resample that happens to draw only
 * zero-call skills evaluates to NaN — and `Array.prototype.sort` leaves the
 * position of a NaN undefined, which would corrupt the percentile lookup and
 * could even return NaN as a bound. Dropping those draws and taking the
 * percentiles of the remaining ones is the correct treatment: they carry no
 * information about the estimand.
 *
 * When every draw is non-finite the interval is NaN (and the caller reports it
 * as such rather than inventing a bound).
 */
function ciFromDistribution(dist: number[], mean: number): CI {
  const finite = dist.filter(Number.isFinite)
  if (finite.length === 0)
    return { mean, lo: Number.NaN, hi: Number.NaN }
  finite.sort((a, b) => a - b)
  return { mean, lo: percentile(finite, 0.025), hi: percentile(finite, 0.975) }
}

export interface CI {
  /** Point estimate (sample mean). */
  mean: number
  /** Lower bound of the (default 95%) interval. */
  lo: number
  /** Upper bound. */
  hi: number
}

/**
 * Percentile bootstrap CI for the mean.
 *
 * Method: resample with replacement `iterations` times, compute the mean of
 * each resample, take the 2.5/97.5 percentiles.
 *
 * @note This is the **percentile** bootstrap. For proportion-type estimators at
 * small sample sizes the percentile method has known coverage-probability bias
 * (the true coverage can be below the nominal level, especially near 0/1
 * boundaries). Prefer {@link bcaBootstrapCI} when a coverage-correct interval
 * matters; the two share the same resampling unit (skills), which is correct.
 */
export function bootstrapCI(
  values: number[],
  opts: { iterations?: number, seed?: number } = {},
): CI {
  const iterations = opts.iterations ?? 10000
  const rng = mulberry32(opts.seed ?? 0x9E3779B9)
  const n = values.length
  if (n === 0)
    return { mean: Number.NaN, lo: Number.NaN, hi: Number.NaN }

  const sampleMean = values.reduce((a, b) => a + b, 0) / n
  const means: number[] = Array.from({ length: iterations })
  for (let i = 0; i < iterations; i++) {
    let s = 0
    for (let j = 0; j < n; j++)
      s += values[Math.floor(rng() * n)]
    means[i] = s / n
  }
  means.sort((a, b) => a - b)
  return ciFromDistribution(means, sampleMean)
}

export interface DiDResult {
  /** Point estimate = (D - C) - (B - A) over cell means. */
  estimate: number
  ci: CI
  /** The four cell means used. */
  cellMeans: { a: number, b: number, c: number, d: number }
}

/**
 * Difference-in-differences for a 2x2 with rows = selfVerification (0/1) and
 * columns = envFeedback (0/1).
 *
 *   A = (SV off, env off)   B = (SV off, env on)
 *   C = (SV on,  env off)   D = (SV on,  env on)
 *
 * DiD = (mean(D) - mean(C)) - (mean(B) - mean(A)) = D - C - B + A.
 *
 * Kept for backward compatibility. The headline RQ-C inference now uses the
 * skill-level chi-square / McNemar / factorial log-odds interaction (see
 * `harness.ts`); this per-unit-mean DiD is a complementary descriptive
 * quantity, not the primary test.
 *
 * @param A array of per-unit values (e.g. per-skill precision) for cell A, etc.
 */
export function differenceInDifferences(
  A: number[],
  B: number[],
  C: number[],
  D: number[],
  opts: { iterations?: number, seed?: number } = {},
): DiDResult {
  const iterations = opts.iterations ?? 10000
  const rng = mulberry32(opts.seed ?? 0x1234567)
  const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : Number.NaN)
  const point = mean(D) - mean(C) - mean(B) + mean(A)

  const dist: number[] = Array.from({ length: iterations })
  for (let i = 0; i < iterations; i++) {
    const dA = resample(A, rng)
    const dB = resample(B, rng)
    const dC = resample(C, rng)
    const dD = resample(D, rng)
    dist[i] = mean(dD) - mean(dC) - mean(dB) + mean(dA)
  }
  dist.sort((a, b) => a - b)
  return {
    estimate: point,
    ci: ciFromDistribution(dist, point),
    cellMeans: { a: mean(A), b: mean(B), c: mean(C), d: mean(D) },
  }
}

function resample(xs: number[], rng: () => number): number[] {
  const n = xs.length
  if (n === 0)
    return []
  const out: number[] = Array.from({ length: n })
  for (let i = 0; i < n; i++)
    out[i] = xs[Math.floor(rng() * n)]
  return out
}

/** Abramowitz & Stegun 7.1.26 error-function approximation (max err ~1.5e-7). */
export function erf(x: number): number {
  const sign = x < 0 ? -1 : 1
  const ax = Math.abs(x)
  const t = 1 / (1 + 0.3275911 * ax)
  const y
    = 1
      - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592)
      * t
      * Math.exp(-ax * ax)
  return sign * y
}

/** Standard normal CDF, using the erf approximation. */
export function normalCdf(x: number): number {
  return 0.5 * (1 + erf(x / Math.SQRT2))
}

/**
 * Standard normal **survival function** sf(x) = P(Z > x), accurate deep into
 * the far tail.
 *
 * ## Why this exists
 *
 * The upper tail was previously computed as `1 - normalCdf(x)`. That is a
 * difference of two numbers which both round to 1 once x ≳ 8, and the A&S erf
 * approximation additionally carries a ~1.5e-7 absolute error. Above x ≈ 5 the
 * subtraction is therefore pure rounding noise, and the two-sided p-value
 * collapses to exactly 0:
 *
 *   | χ² (1 df) | `2·(1 − normalCdf(√χ²))` | true p      |
 *   |-----------|--------------------------|-------------|
 *   | 32.358    | 1.286e-8 (2.9e-3 rel err)| 1.282e-8    |
 *   | 64.721    | 8.882e-16 (2.9e-2 rel err)| 8.629e-16   |
 *   | 100       | 0 (underflow)            | 1.524e-23   |
 *   | 200       | 0 (underflow)            | 2.089e-45   |
 *
 * A McNemar result of χ² = 64.721 can therefore only be written up as
 * "p < 1e-4" instead of its actual magnitude, and anything beyond χ² ≈ 90 is
 * reported as p = 0. This function removes that ceiling.
 *
 * ## Method
 *
 * Two branches, both ~1e-15 relative:
 * - `x ≥ 2` — Laplace continued fraction
 *     `sf(x) = φ(x) / (x + 1/(x + 2/(x + 3/(x + …))))`
 *   evaluated backwards. It is cancellation-free and underflows only below
 *   sf ≈ 1e-308 (x ≈ 38).
 * - `|x| < 2` — Maclaurin series of erf,
 *     `erf(x) = (2/√π) Σₙ (−1)ⁿ x^(2n+1) / (n! (2n+1))`,
 *   which converges to double precision in ~25 terms over that range.
 *
 * The branches agree to ~1e-13 absolute at the x = 2 seam (≈4e-12 relative to
 * sf(2) = 0.0228), far below any meaningful threshold.
 *
 * @see normalCdf for the central-region CDF (unchanged, still A&S-based).
 */
export function normalSf(x: number): number {
  if (Number.isNaN(x))
    return Number.NaN
  if (x === Number.POSITIVE_INFINITY)
    return 0
  if (x === Number.NEGATIVE_INFINITY)
    return 1
  if (x >= 2)
    return normalSfTailCF(x)
  if (x <= -2)
    return 1 - normalSfTailCF(-x)
  return 0.5 * (1 - erfSeries(x / Math.SQRT2))
}

/**
 * Laplace continued fraction for sf(x), used for x >= 2.
 *
 * Convergence is slowest at the smallest x in the branch (x = 2), where the
 * depth-`d` truncation error against a depth-4000 reference is
 * `3.5e-9` at d = 32, `3.5e-13` at d = 64 and `4.6e-16` at d = 96. Depth 128
 * therefore reproduces the converged value to the last bit across the whole
 * branch, at a cost of ~128 divisions per p-value.
 */
function normalSfTailCF(x: number): number {
  let f = 0
  for (let k = 128; k >= 1; k--)
    f = k / (x + f)
  return Math.exp((-x * x) / 2) / Math.sqrt(2 * Math.PI) / (x + f)
}

/** Maclaurin series for erf(x); used only for |x| < √2, where it is exact to ~1e-16. */
function erfSeries(x: number): number {
  const x2 = x * x
  let term = x
  let sum = x
  for (let n = 1; n < 200; n++) {
    term *= -x2 / n
    const add = term / (2 * n + 1)
    sum += add
    if (Math.abs(add) <= Number.EPSILON * Math.abs(sum))
      break
  }
  return (2 / Math.sqrt(Math.PI)) * sum
}

/**
 * Two-sided p-value for a standard normal deviate: `2 · sf(|z|)`.
 *
 * Use this instead of `2 * (1 - normalCdf(|z|))` for every p-value in this
 * module; identical in the mid-range, but defined (and correct) in the tail.
 */
export function twoSidedNormalP(z: number): number {
  return 2 * normalSf(Math.abs(z))
}

/**
 * Inverse standard normal CDF (probit) — Acklam's rational approximation
 * (max relative error ~1.15e-9). Pure; no lookup tables.
 */
export function normalQuantile(p: number): number {
  if (p <= 0)
    return -Infinity
  if (p >= 1)
    return Infinity
  const a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
  const b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01]
  const c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
  const d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
  const plow = 0.02425
  const phigh = 1 - plow
  let q: number
  let r: number
  if (p < plow) {
    q = Math.sqrt(-2 * Math.log(p))
    return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
      / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
  }
  if (p <= phigh) {
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
      / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
  }
  q = Math.sqrt(-2 * Math.log(1 - p))
  return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
    / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
}

export interface ChiSquareResult {
  statistic: number
  /** Upper-tail p-value (survival function) of chi-square with 1 df. */
  p: number
  table: number[][]
  df: number
}

/**
 * Pearson chi-square for a 2x2 contingency table:
 *
 *   [ [a, b],
 *     [c, d] ]
 *
 * With `useYates` (default true) the Yates continuity correction is applied,
 * which is appropriate for 1-df tables. The p-value uses the fact that a
 * chi-square with 1 df equals (standard normal)^2, so
 * p = P(X^2 > stat) = 2 * (1 - Phi(sqrt(stat))).
 */
export function chiSquare2x2(
  a: number,
  b: number,
  c: number,
  d: number,
  useYates = true,
): ChiSquareResult {
  const table: number[][] = [[a, b], [c, d]]
  const row0 = a + b
  const row1 = c + d
  const col0 = a + c
  const col1 = b + d
  const n = a + b + c + d
  if (n === 0)
    return { statistic: 0, p: 1, table, df: 1 }

  const cross = a * d - b * c
  const denom = row0 * row1 * col0 * col1
  // A zero margin means the association is *undefined*, not infinite: no
  // outcome varies along that dimension, so the table carries no information.
  // Without this guard the division below is 0/0 → NaN, and that NaN then leaks
  // into holmBonferroni and destroys the adjusted p-values of every other
  // hypothesis in the same family. Returning p = 1 (no evidence) is the correct
  // and inert answer.
  if (denom === 0)
    return { statistic: 0, p: 1, table, df: 1 }

  let stat = (n * cross * cross) / denom
  if (useYates) {
    const adj = Math.max(0, Math.abs(cross) - n / 2)
    stat = (n * adj * adj) / denom
  }
  const p = stat <= 0 ? 1 : twoSidedNormalP(Math.sqrt(stat))
  return { statistic: stat, p, table, df: 1 }
}

// ---------------------------------------------------------------------------
// Skill-level (pooled-precision) bootstrap — the canonical resampling used by
// the harness. Defined here so the harness reuses one implementation instead of
// keeping an inline copy whose semantics could drift from the exported one.
// ---------------------------------------------------------------------------

/** A skill collapsed to its success / call counts (the resampling unit). */
export interface SkillCount {
  succ: number
  calls: number
}

/** Pooled precision = sum(succ) / sum(calls) across a set of skills. */
export function pooledPrecision(skills: SkillCount[]): number {
  const calls = skills.reduce((a, s) => a + s.calls, 0)
  if (calls === 0)
    return Number.NaN
  return skills.reduce((a, s) => a + s.succ, 0) / calls
}

/**
 * Percentile bootstrap CI for **pooled** precision.
 *
 * Resamples skills *with replacement* and recomputes the pooled precision
 * (sum succ / sum calls) each time — the exact same definition used by the
 * headline 4-cell table. This deliberately differs from {@link bootstrapCI},
 * which resamples per-unit values and takes their *mean*; the two must not be
 * mixed, or the same cell would report two different precisions.
 */
export function bootstrapPooledPrecision(
  skills: SkillCount[],
  opts: { iterations?: number, seed?: number } = {},
): CI {
  const iterations = opts.iterations ?? 10000
  const rng = mulberry32(opts.seed ?? 0x9E3779B9)
  const n = skills.length
  if (n === 0)
    return { mean: Number.NaN, lo: Number.NaN, hi: Number.NaN }

  const point = pooledPrecision(skills)
  const means: number[] = Array.from({ length: iterations })
  for (let i = 0; i < iterations; i++) {
    let succ = 0
    let calls = 0
    for (let j = 0; j < n; j++) {
      const s = skills[Math.floor(rng() * n)]
      succ += s.succ
      calls += s.calls
    }
    means[i] = calls === 0 ? Number.NaN : succ / calls
  }
  means.sort((a, b) => a - b)
  return ciFromDistribution(means, point)
}

/**
 * Difference-in-differences on **pooled** precision (consistent with the
 * headline 4-cell table). Resamples each cell's skills and recomputes pooled
 * precision, then DiD = (D - C) - (B - A). Returns the same shape as
 * {@link differenceInDifferences} so the harness can switch implementations
 * without changing its result object.
 */
export function pooledDifferenceInDifferences(
  A: SkillCount[],
  B: SkillCount[],
  C: SkillCount[],
  D: SkillCount[],
  opts: { iterations?: number, seed?: number } = {},
): DiDResult {
  const iterations = opts.iterations ?? 10000
  const rng = mulberry32(opts.seed ?? 0x1234567)
  const resamplePooled = (skills: SkillCount[]): number => {
    const n = skills.length
    if (n === 0)
      return Number.NaN
    let succ = 0
    let calls = 0
    for (let j = 0; j < n; j++) {
      const s = skills[Math.floor(rng() * n)]
      succ += s.succ
      calls += s.calls
    }
    return calls === 0 ? Number.NaN : succ / calls
  }
  const point = pooledPrecision(D) - pooledPrecision(C) - pooledPrecision(B) + pooledPrecision(A)
  const dist: number[] = Array.from({ length: iterations })
  for (let i = 0; i < iterations; i++) {
    dist[i] = resamplePooled(D) - resamplePooled(C) - resamplePooled(B) + resamplePooled(A)
  }
  dist.sort((a, b) => a - b)
  return {
    estimate: point,
    ci: ciFromDistribution(dist, point),
    cellMeans: {
      a: pooledPrecision(A),
      b: pooledPrecision(B),
      c: pooledPrecision(C),
      d: pooledPrecision(D),
    },
  }
}

// ---------------------------------------------------------------------------
// Effect sizes (journal requirement: report more than a p-value)
// ---------------------------------------------------------------------------

/** Haldane 0.5 correction applied to all four cells when any is zero. */
function haldane(a: number, b: number, c: number, d: number): [number, number, number, number] {
  if (a === 0 || b === 0 || c === 0 || d === 0)
    return [a + 0.5, b + 0.5, c + 0.5, d + 0.5]
  return [a, b, c, d]
}

/**
 * Odds ratio of a 2x2 contingency table `[[a, b], [c, d]]`: OR = a·d / (b·c).
 * With 0.5 continuity correction when a cell is empty. Returns the point estimate.
 */
export function oddsRatio(a: number, b: number, c: number, d: number): number {
  const [A, B, C, D] = haldane(a, b, c, d)
  return (A * D) / (B * C)
}

/**
 * Risk difference of a 2x2: P(row 0 success) − P(row 1 success)
 * = a/(a+b) − c/(c+d). With 0.5 continuity correction when a cell is empty.
 */
export function riskDifference(a: number, b: number, c: number, d: number): number {
  const [A, B, C, D] = haldane(a, b, c, d)
  return (A / (A + B)) - (C / (C + D))
}

/**
 * Cramér's V from a chi-square statistic and the total N. For a 2x2 table
 * `min(r-1, c-1) = 1`, so V = sqrt(χ² / N). Bounded in [0, 1].
 */
export function cramersV(chiSquareStat: number, n: number): number {
  if (n <= 0)
    return Number.NaN
  return Math.sqrt(Math.max(0, chiSquareStat) / n)
}

/**
 * Cohen's h — effect size for the difference between two proportions.
 * h = 2·asin(√p1) − 2·asin(√p2).
 */
export function cohensH(p1: number, p2: number): number {
  const asinSqrt = (p: number) => Math.asin(Math.sqrt(Math.min(1, Math.max(0, p))))
  return 2 * asinSqrt(p1) - 2 * asinSqrt(p2)
}

export interface LogOddsInteractionResult {
  /** log(a·d / (b·c)) — the log product-ratio of the 2x2. */
  estimate: number
  /** Woolf standard error √(1/a + 1/b + 1/c + 1/d) (after correction). */
  se: number
  /** z = estimate / se. */
  z: number
  /** Two-sided p-value from the standard normal. */
  p: number
}

/**
 * Log-odds interaction of a 2x2 factorial table `[[a, b], [c, d]]`:
 * estimate = log(a·d / (b·c)), SE = √(1/a + 1/b + 1/c + 1/d),
 * z = estimate/se, p two-sided from the normal CDF.
 *
 * Used for the RQ-C "2×2 factorial interaction" (selfVerification × envFeedback)
 * on the log-odds scale, replacing the old (mislabeled) "DiD". A 0.5 Haldane
 * correction is applied to every cell when any is zero, so the log is finite.
 *
 * @note For RQ-C the four cells are the four (sv, ef) *success counts*:
 * `a = (sv0, ef0)`, `b = (sv0, ef1)`, `c = (sv1, ef0)`, `d = (sv1, ef1)`.
 * This is the reviewer-specified product-ratio form; a fully conditional
 * logistic interaction would also enter each cell's failures, which the
 * separate skill-level 2x2 (OR / RD / Cramér's V) already captures.
 */
export function logOddsInteraction(a: number, b: number, c: number, d: number): LogOddsInteractionResult {
  const [A, B, C, D] = haldane(a, b, c, d)
  const estimate = Math.log((A * D) / (B * C))
  const se = Math.sqrt(1 / A + 1 / B + 1 / C + 1 / D)
  const z = se === 0 ? 0 : estimate / se
  const p = se === 0 ? (estimate === 0 ? 1 : 0) : twoSidedNormalP(z)
  return { estimate, se, z, p }
}

// ---------------------------------------------------------------------------
// McNemar paired test (envFeedback ON vs OFF, same skills paired)
// ---------------------------------------------------------------------------

export interface McNemarResult {
  /** Pairs: both fail. */
  a: number
  /** OFF fail, ON pass (envFeedback helped). */
  b: number
  /** OFF pass, ON fail (envFeedback hurt). */
  c: number
  /** Both pass. */
  d: number
  /** Total paired skills with a defined outcome. */
  nPairs: number
  /** McNemar chi-square (continuity-corrected) on the discordant cells. */
  chiSquare: number
  /** p-value from the chi-square form. */
  pChiSquare: number
  /** Exact two-sided binomial p (non-null only when discordant < 25). */
  pExact: number | null
  /** Recommended p: exact when discordant < 25, else chi-square. */
  p: number
  /** Whether the exact binomial test was used. */
  usedExact: boolean
}

/**
 * McNemar's test for paired binary outcomes (envFeedback ON vs OFF, skills
 * paired by trial × task). Table:
 *
 *   a = OFF fail & ON fail     b = OFF fail & ON pass
 *   c = OFF pass & ON fail     d = OFF pass & ON pass
 *
 * When the number of discordant pairs (b + c) is < 25 the exact two-sided
 * binomial test (X ~ Bin(b+c, 0.5)) is used; otherwise the continuity-corrected
 * McNemar chi-square is reported. This is valid because the block design
 * (B4) guarantees the same task set under both conditions.
 */
export function mcnemarExactOrChi(a: number, b: number, c: number, d: number): McNemarResult {
  const nPairs = a + b + c + d
  const discordant = b + c
  const stat = discordant === 0 ? 0 : ((Math.abs(b - c) - 1) ** 2) / discordant
  const pChi = stat <= 0 ? 1 : twoSidedNormalP(Math.sqrt(stat))

  let pExact: number | null = null
  let usedExact = false
  if (discordant > 0 && discordant < 25) {
    pExact = exactBinomialTwoSided(b, discordant)
    usedExact = true
  }
  const p = usedExact && pExact !== null ? pExact : pChi
  return { a, b, c, d, nPairs, chiSquare: stat, pChiSquare: pChi, pExact, p, usedExact }
}

/** Two-sided binomial p under H0 p = 0.5: P(X ≤ min) + P(X ≥ max). */
function exactBinomialTwoSided(x: number, n: number): number {
  const pmf = (k: number) => Math.exp(lnChoose(n, k) - n * Math.log(2))
  const lo = Math.min(x, n - x)
  const hi = Math.max(x, n - x)
  let p = 0
  for (let k = 0; k <= lo; k++)
    p += pmf(k)
  for (let k = hi; k <= n; k++)
    p += pmf(k)
  return Math.min(1, p)
}

/** ln(C(n, k)) via a stable log-gamma-free loop (n is small here). */
function lnChoose(n: number, k: number): number {
  if (k < 0 || k > n)
    return -Infinity
  k = Math.min(k, n - k)
  let s = 0
  for (let i = 1; i <= k; i++)
    s += Math.log((n - k + i) / i)
  return s
}

// ---------------------------------------------------------------------------
// Holm step-down (multiple-comparison correction)
// ---------------------------------------------------------------------------

export interface HolmStep {
  label: string
  /** Original (unadjusted) p-value. */
  p: number
  /** Holm-adjusted p-value. */
  adjustedP: number
  /** Reject H0 at the family-wise alpha. */
  reject: boolean
}

/**
 * Holm step-down procedure (not BH, not plain Bonferroni).
 *
 * Sorts p-values ascending, compares the k-th smallest against
 * α / (m − k + 1); rejects while the sequence holds. Adjusted p-values are the
 * standard monotone step-down bounds, floored at 1.
 *
 * ## Non-finite p-values
 *
 * Only *finite* p-values enter the family. A NaN (which a degenerate 2x2 could
 * previously produce) or an infinite p is not a testable hypothesis, so letting
 * it occupy a rank would silently inflate the correction for every other member
 * of the family — one bad cell would make a genuinely significant result
 * non-significant. Such entries are returned with `adjustedP = NaN` and
 * `reject = false`, and the remaining hypotheses are corrected against
 * `m = ` the number of testable p-values.
 */
export function holmBonferroni(
  pValues: number[],
  alpha = 0.05,
  labels?: string[],
): HolmStep[] {
  const m = pValues.length
  if (m === 0)
    return []

  const testable = pValues
    .map((p, i) => ({ p, i }))
    .filter(entry => Number.isFinite(entry.p))
    .sort((x, y) => x.p - y.p)

  const adjustedByIndex = new Map<number, number>()
  let prev = 0
  for (let k = 0; k < testable.length; k++) {
    const adj = Math.min(1, testable[k].p * (testable.length - k))
    const monotone = Math.max(adj, prev)
    adjustedByIndex.set(testable[k].i, monotone)
    prev = monotone
  }

  return pValues.map((p, i) => {
    const adjustedP = adjustedByIndex.get(i)
    return {
      label: labels?.[i] ?? String(i),
      p,
      adjustedP: adjustedP ?? Number.NaN,
      reject: adjustedP !== undefined && adjustedP <= alpha,
    }
  })
}

// ---------------------------------------------------------------------------
// BCa bootstrap (bias-corrected accelerated) — coverage-correct alternative to
// the percentile method.
// ---------------------------------------------------------------------------

/**
 * BCa (bias-corrected accelerated) bootstrap CI for the mean.
 *
 * @param values the sample.
 * @param opts bootstrap options.
 * @param opts.iterations bootstrap iterations (default 10000).
 * @param opts.seed PRNG seed for reproducibility.
 * @param opts.confidence nominal level (default 0.95).
 *
 * @note Boundary handling: returns NaN-filled CI when n < 2 (cannot resample
 * or jackknife). When all values are equal the acceleration `a = 0` and the
 * result collapses to the percentile CI (= the point estimate), which is
 * correct. Ties in the bootstrap distribution are handled by the percentile
 * interpolation already used elsewhere.
 */
export function bcaBootstrapCI(
  values: number[],
  opts: { iterations?: number, seed?: number, confidence?: number } = {},
): CI {
  const iterations = opts.iterations ?? 10000
  const confidence = opts.confidence ?? 0.95
  const rng = mulberry32(opts.seed ?? 0x9E3779B9)
  const n = values.length
  if (n < 2)
    return { mean: Number.NaN, lo: Number.NaN, hi: Number.NaN }

  const orig = values.reduce((a, b) => a + b, 0) / n
  const means: number[] = Array.from({ length: iterations })
  for (let i = 0; i < iterations; i++) {
    let s = 0
    for (let j = 0; j < n; j++)
      s += values[Math.floor(rng() * n)]
    means[i] = s / n
  }
  const finite = means.filter(Number.isFinite)
  if (finite.length === 0)
    return { mean: orig, lo: Number.NaN, hi: Number.NaN }
  finite.sort((a, b) => a - b)

  // Bias correction z0. The rank fraction is clamped away from {0, 1}: with tied
  // or discrete data the original statistic can sit at (or beyond) the entire
  // bootstrap distribution, and normalQuantile(0 | 1) = ∓Infinity would make
  // every bound NaN.
  let below = 0
  for (const m of finite) {
    if (m <= orig)
      below++
  }
  const frac = Math.min(
    1 - 1 / (finite.length + 1),
    Math.max(1 / (finite.length + 1), below / finite.length),
  )
  const z0 = normalQuantile(frac)

  // Acceleration a from the jackknife.
  const total = values.reduce((a, b) => a + b, 0)
  let sumCubed = 0
  let sumSq = 0
  for (const v of values) {
    const jack = (total - v) / (n - 1)
    const dev = orig - jack
    sumCubed += dev * dev * dev
    sumSq += dev * dev
  }
  const a = sumSq === 0 ? 0 : sumCubed / (6 * (sumSq ** 1.5))

  const alphaLo = (1 - confidence) / 2
  const alphaHi = 1 - alphaLo
  const zAlphaLo = normalQuantile(alphaLo)
  const zAlphaHi = normalQuantile(alphaHi)

  const pLo = normalCdf(z0 + (z0 + zAlphaLo) / (1 - a * (z0 + zAlphaLo)))
  const pHi = normalCdf(z0 + (z0 + zAlphaHi) / (1 - a * (z0 + zAlphaHi)))

  const lo = percentile(finite, Math.min(1, Math.max(0, pLo)))
  const hi = percentile(finite, Math.min(1, Math.max(0, pHi)))
  return { mean: orig, lo, hi }
}

// ---------------------------------------------------------------------------
// Risk-difference confidence interval (Newcombe hybrid score)
// ---------------------------------------------------------------------------

export interface RiskDifferenceCI {
  /** Point estimate a/(a+b) − c/(c+d). */
  estimate: number
  lo: number
  hi: number
}

/** Wilson score interval for a single proportion. */
function wilsonInterval(succ: number, n: number, z: number): [number, number] {
  if (n === 0)
    return [Number.NaN, Number.NaN]
  const p = succ / n
  const z2 = z * z
  const denom = 1 + z2 / n
  const centre = (p + z2 / (2 * n)) / denom
  const half = (z * Math.sqrt((p * (1 - p)) / n + z2 / (4 * n * n))) / denom
  return [centre - half, centre + half]
}

/**
 * Newcombe's hybrid score ("square-and-add") interval for the risk difference
 * `p1 − p2`, with `p1 = a/(a+b)` and `p2 = c/(c+d)`.
 *
 * The point estimate in {@link riskDifference} has no bound in the report. The
 * Wald interval would be the obvious companion, but it degenerates to zero
 * width when either proportion is 0 or 1 — exactly the boundary the RQ-C cells
 * approach. Newcombe's method combines the two **Wilson score** intervals
 * instead and therefore keeps close to nominal coverage at the boundaries:
 *
 *   lo = (p1 − p2) − √((p1 − l1)² + (u2 − p2)²)
 *   hi = (p1 − p2) + √((u1 − p1)² + (p2 − l2)²)
 *
 * where (l1, u1) and (l2, u2) are the Wilson intervals for p1 and p2.
 * Bounds are clamped to [−1, 1], the natural range of a difference of
 * proportions. Returns NaN when either margin is empty (no estimable p).
 *
 * Confidence defaults to 0.95 and is taken from `opts.confidence`.
 */
export function riskDifferenceCI(
  a: number,
  b: number,
  c: number,
  d: number,
  opts: { confidence?: number } = {},
): RiskDifferenceCI {
  const confidence = opts.confidence ?? 0.95
  const n1 = a + b
  const n2 = c + d
  if (n1 === 0 || n2 === 0)
    return { estimate: Number.NaN, lo: Number.NaN, hi: Number.NaN }

  const z = normalQuantile(1 - (1 - confidence) / 2)
  const p1 = a / n1
  const p2 = c / n2
  const estimate = p1 - p2
  const [l1, u1] = wilsonInterval(a, n1, z)
  const [l2, u2] = wilsonInterval(c, n2, z)

  const lo = estimate - Math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
  const hi = estimate + Math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
  return { estimate, lo: Math.max(-1, lo), hi: Math.min(1, hi) }
}

// ---------------------------------------------------------------------------
// Power analysis (declared in the paper)
// ---------------------------------------------------------------------------

/**
 * Minimum detectable effect (proportion scale) for a two-proportion z-test at
 * skill level, equal n per cell, baseline p0, two-sided alpha and target power.
 *
 * Solves for δ in p1 = p0 − δ/2, p2 = p0 + δ/2 such that the required per-cell
 * n equals `nPerCell`:
 *   n = (z_{α/2} + z_β)² · (p1(1−p1) + p2(1−p2)) / δ²
 *
 * @returns δ as a proportion (multiply by 100 for percentage points).
 */
export function minDetectableEffectProportion(
  nPerCell: number,
  opts: { p0?: number, alpha?: number, power?: number } = {},
): number {
  const p0 = opts.p0 ?? 0.5
  const alpha = opts.alpha ?? 0.05
  const power = opts.power ?? 0.8
  const zA = normalQuantile(1 - alpha / 2)
  const zB = normalQuantile(power)
  // f(δ) > 0 means we would need MORE than nPerCell skills -> δ too small.
  const f = (delta: number): number => {
    const p1 = p0 - delta / 2
    const p2 = p0 + delta / 2
    const v = p1 * (1 - p1) + p2 * (1 - p2)
    const nReq = (zA + zB) ** 2 * v / (delta * delta)
    return nReq - nPerCell
  }
  if (nPerCell <= 0)
    return Number.NaN
  if (f(1) > 0)
    return 1
  let lo = 1e-6
  let hi = 1
  for (let i = 0; i < 100; i++) {
    const mid = (lo + hi) / 2
    if (f(mid) > 0)
      lo = mid
    else hi = mid
  }
  return (lo + hi) / 2
}

/**
 * Achieved power of the two-proportion z-test for a *given* effect `delta`
 * (proportion scale), equal n per cell, baseline `p0`, two-sided `alpha`.
 *
 * This is the inverse of {@link minDetectableEffectProportion}: where that
 * function answers "how small an effect can I still detect at 80% power?",
 * this one answers "what power do I actually have for an effect of size δ at
 * my achieved n?". It uses the standard (unpooled, under-H1) two-proportion
 * power formula:
 *
 *   SE = √( p0(1−p0)/n + p1(1−p1)/n ),  p1 = p0 + δ
 *   z  = (p1 − p0) / SE
 *   power = Φ(z − z_{α/2})
 *
 * @note The review's §1.8 reference values (e.g. Δ=10pp → 0.56/0.74) are
 * reproduced here from a *derived* formula, NOT hard-coded, because the project
 * has a history of wrong hand-typed reference numbers. Callers should report
 * whatever this returns and state the qualitative conclusion ("at the achieved
 * n the design can only resolve effects of roughly ≥10pp").
 */
export function powerForEffectProportion(
  delta: number,
  nPerCell: number,
  opts: { p0?: number, alpha?: number } = {},
): number {
  const p0 = opts.p0 ?? 0.5
  const alpha = opts.alpha ?? 0.05
  if (nPerCell <= 0)
    return Number.NaN
  const p1 = p0 + delta
  if (p1 <= 0 || p1 >= 1)
    return Number.NaN
  const se = Math.sqrt(p0 * (1 - p0) / nPerCell + p1 * (1 - p1) / nPerCell)
  if (se <= 0)
    return Number.NaN
  const z = (p1 - p0) / se
  const zA = normalQuantile(1 - alpha / 2)
  return normalCdf(z - zA)
}
