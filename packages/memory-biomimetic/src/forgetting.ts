import type { ForgettingConfig, GatingCoefficients } from './types'

import { decayExponent } from './gating'

export interface StrengthInput {
  createdAt: number
  accessCount: number
  baseStrength: number
  durability: number
}

/**
 * Retrieval strength at time `now`.
 *
 *   strength = baseStrength · durability · spacing / (1 + age/ageScale)^decay
 *
 * - `durability` bakes in the **content-salience** gating (set at encode time):
 *   salient memories carry >1, so they decay slower in absolute terms.
 * - `decay` is modulated by the memory's **content salience** (not cortisol):
 *   higher salience → smaller exponent → slower forgetting. Under NO_GATING this
 *   collapses to the base power law for everyone.
 * - `spacing` is the spacing-effect term (pure forgetting-config, applies in
 *   both conditions — it is not a physiological gate).
 */
export function retrievalStrength(
  item: StrengthInput,
  now: number,
  f: ForgettingConfig,
  g: GatingCoefficients,
  salience: number,
): number {
  const age = Math.max(0, now - item.createdAt)
  const ageNorm = age / f.ageScaleMs
  const decay = (1 + ageNorm) ** decayExponent(salience, f.baseDecay, g)
  const spacing = (1 + item.accessCount) ** f.spacingBeta
  return (item.baseStrength * item.durability * spacing) / decay
}
