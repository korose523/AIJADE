import type { ContentSalience, GatingCoefficients } from './types'

function clamp01(x: number): number {
  return Math.min(1, Math.max(0, x))
}

/**
 * Durability multiplier applied to a memory at encode/consolidation time.
 *
 * Under NO_GATING (all coefficients 0) this is exactly 1 for every memory,
 * so the model reduces to ungated decay — the control condition. Under
 * DEFAULT_GATING, salient (high-content-salience / high-social) memories get
 * >1 and therefore survive forgetting longer.
 */
export function durability(sal: ContentSalience, g: GatingCoefficients): number {
  return 1 + g.kSalience * clamp01(sal.salience) + g.kSocial * clamp01(sal.socialSalience)
}

/**
 * Decay exponent: driven by **content salience** (not cortisol). Salient
 * memories decay slower. Under NO_GATING this collapses to the base power law
 * for everyone.
 */
export function decayExponent(salience: number, baseDecay: number, g: GatingCoefficients): number {
  return baseDecay * (1 + g.kSalience * (1 - clamp01(salience)))
}

/**
 * Retrieval breadth (how many weaker candidates to consider). Driven by the
 * novelty coefficient — curiosity from content novelty, not adrenaline.
 */
export function retrievalBreadth(g: GatingCoefficients): number {
  return g.kNovelty
}
