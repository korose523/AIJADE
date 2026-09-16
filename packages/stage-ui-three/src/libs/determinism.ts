/**
 * determinism — deterministic PRNG + helpers for the *presentation layer* of
 * stage-ui-three (avatar idle gestures, blinking, eye-saccades).
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * WHY A SEPARATE COPY OF mulberry32 (instead of importing the research kernel)?
 * ─────────────────────────────────────────────────────────────────────────────
 * The research kernel (packages/growth-services, packages/memory-biomimetic,
 * packages/research-harness) already forbids `Math.random()` and drives every
 * computed value through a seeded mulberry32 so results are byte-for-byte
 * replayable. The *presentation* layer was the one remaining place still
 * calling `Math.random()`, which made the project's "the render is replayable"
 * design goal mathematically false.
 *
 * This module intentionally re-implements mulberry32 rather than importing it
 * from the research kernel. Reason: the presentation layer must not take a
 * compile/runtime dependency on research-kernel packages (different build &
 * version lifecycle, and it would drag a non-UI package into the 3D bundle).
 *
 * The two copies MUST stay bit-identical. That invariant is locked by the
 * cross-implementation test in `determinism.test.ts`, which asserts the first
 * outputs of `mulberry32(7)` equal literal constants derived from the
 * research-kernel copy of the *same* algorithm
 * (packages/growth-services/src/metrics/stats.ts). If someone edits either
 * copy, that test fails loudly instead of letting the two silently diverge.
 */

/**
 * mulberry32 — small, fast, seedable PRNG returning floats in [0, 1).
 *
 * Bit-for-bit identical to `packages/growth-services/src/metrics/stats.ts`.
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

/**
 * FNV-1a (32-bit) string hash -> a non-zero integer seed.
 *
 * Returns `>>> 0` so the result is always a valid unsigned 32-bit seed.
 * The result can never be 0: a zero seed makes mulberry32 degenerate
 * (every draw returns 0), which would collapse an entire RNG stream.
 */
export function hashStringToSeed(input: string): number {
  let h = 0x811C9DC5
  for (let i = 0; i < input.length; i++)
    h = Math.imul(h ^ input.charCodeAt(i), 0x01000193)
  return (h >>> 0) || 0x1
}

/**
 * Deterministically pick one element from `pool` using an injected RNG.
 *
 * @param rng  source of randomness; must return floats in [0, 1). This is the
 *             sole source of determinism — pass a `mulberry32(seed)` stream to
 *             make picks reproducible.
 * @param pool candidate elements.
 * @returns    the chosen element (always a member of `pool`).
 *
 * CONTRACT (locked by `determinism.test.ts`): throws `RangeError` when `pool`
 * is empty or `undefined`. There is no deterministic value to return in that
 * case, and silently yielding `undefined` would hide a caller bug — so we fail
 * loudly instead. Picking can therefore never run outside `pool`.
 */
export function pickSeeded<T>(rng: () => number, pool: readonly T[]): T {
  if (!pool || pool.length === 0)
    throw new RangeError('pickSeeded: pool must be a non-empty array')
  return pool[Math.floor(rng() * pool.length)]!
}

/** Clamp a number into the closed interval [0, 1]. */
export function clamp01(x: number): number {
  return Math.max(0, Math.min(1, x))
}
