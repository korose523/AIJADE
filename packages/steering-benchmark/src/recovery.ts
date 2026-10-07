// Recovery metrics (ToolMaze-style PRR / Recovery Cost, reimplemented as our own).
// MOSAIC / ToolMaze define Perturbation Recovery Rate (PRR) and Recovery Cost;
// we reproduce the *concept* with original code, no dependency.

import type { BehaviorTrace } from './perturbation'

/**
 * Perturbation Recovery Rate: fraction of reference-ok steps that were broken by
 * the perturbation AND restored by the recovered trace.
 * Returns 1 when nothing was actually affected.
 */
export function perturbationRecoveryRate(
  reference: BehaviorTrace,
  perturbed: BehaviorTrace,
  recovered: BehaviorTrace,
): number {
  const affectedIdx: number[] = []
  reference.steps.forEach((s, i) => {
    if (s.ok && !perturbed.steps[i].ok)
      affectedIdx.push(i)
  })
  if (affectedIdx.length === 0)
    return 1
  const restored = affectedIdx.filter(i => recovered.steps[i].ok).length
  return restored / affectedIdx.length
}

/**
 * Recovery Cost: number of reference-ok steps that remain broken in the recovered
 * trace (i.e. were not recovered). Lower is better.
 */
export function recoveryCost(
  reference: BehaviorTrace,
  perturbed: BehaviorTrace,
  recovered: BehaviorTrace,
): number {
  let cost = 0
  reference.steps.forEach((s, i) => {
    if (s.ok && !perturbed.steps[i].ok && !recovered.steps[i].ok)
      cost++
  })
  return cost
}
