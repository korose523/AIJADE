/**
 * §5.5 — Deterministic statistics for the pilot (no `Math.random()`).
 *
 * The paper mandates bootstrap 95% CIs, effect sizes and Bonferroni correction.
 * All resampling is driven by an explicit integer `seed` via a seeded PRNG, so the
 * pilot is byte-for-byte reproducible. Every helper here is a pure function.
 */

/**
 * mulberry32 — small, fast, seedable PRNG returning floats in [0, 1).
 * Uses only `Math.imul` (deterministic); never calls `Math.random()`.
 */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return function () {
    a = (a + 0x6D2B79F5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function mean(xs: number[]): number {
  if (xs.length === 0)
    return 0
  return xs.reduce((a, b) => a + b, 0) / xs.length
}

function variance(xs: number[], m: number): number {
  if (xs.length < 2)
    return 0
  const s = xs.reduce((a, b) => a + (b - m) * (b - m), 0)
  return s / (xs.length - 1)
}

/**
 * Bootstrap 95% percentile confidence interval of the mean.
 *
 * Resamples `values` with replacement `iterations` times (seeded), returns the
 * [2.5%, 97.5%] quantiles of the resampled means. With `n` source samples this is
 * a deliberately lightweight pilot estimate — see report limitations.
 *
 * @param values  per-unit observations (e.g. one value per dataset).
 * @param seed    PRNG seed (must be fixed for reproducibility).
 * @param iterations  bootstrap resample count.
 */
export function bootstrapCI(values: number[], seed: number, iterations = 2000): [number, number] {
  const n = values.length
  if (n === 0)
    return [0, 0]
  const rng = mulberry32(seed)
  const means: number[] = []
  for (let i = 0; i < iterations; i++) {
    let s = 0
    for (let j = 0; j < n; j++) {
      const idx = Math.floor(rng() * n) % n
      s += values[idx]
    }
    means.push(s / n)
  }
  means.sort((a, b) => a - b)
  const lo = means[Math.floor(0.025 * (means.length - 1))]
  const hi = means[Math.ceil(0.975 * (means.length - 1))]
  return [lo, hi]
}

/**
 * Cohen's d (pooled standard deviation) between two samples — an effect-size
 * measure (§5.5). Returns 0 when either sample has < 2 elements or pooled SD = 0.
 */
export function cohensD(a: number[], b: number[]): number {
  const na = a.length
  const nb = b.length
  if (na < 2 || nb < 2)
    return 0
  const ma = mean(a)
  const mb = mean(b)
  const va = variance(a, ma)
  const vb = variance(b, mb)
  const pooled = Math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
  if (pooled === 0)
    return 0
  return (ma - mb) / pooled
}

/**
 * Bonferroni correction (§5.5 — paper specifies Bonferroni, not Holm/BH).
 *
 * Given a list of raw p-values (one per comparison against the B0 lower bound),
 * returns the corrected α = α/m and whether each comparison rejects the null.
 */
export function bonferroni(pValues: number[], alpha = 0.05): { correctedAlpha: number, rejected: boolean[] } {
  const m = pValues.length
  const correctedAlpha = alpha / m
  return { correctedAlpha, rejected: pValues.map(p => p <= correctedAlpha) }
}
