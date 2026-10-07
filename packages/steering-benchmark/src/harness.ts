// Steering benchmark harness: T (task dimensions) x P (perturbation kinds), with
// an optional degree-preserving null-model topology signal (MOSAIC's "Connectome
// Randomization" angle, reproduced methodologically).

import type { BehaviorTrace, PerturbationKind } from './perturbation'
import type { Graph } from './randomization'

import { applyPerturbation } from './perturbation'
import { degreePreservingNull, mulberry32 } from './randomization'
import { perturbationRecoveryRate, recoveryCost } from './recovery'

export interface SteeringConfig {
  /** Reference (ideal) behavior traces, keyed by task dimension (T1/T2/T3...). */
  readonly referenceTraces: Readonly<Record<string, BehaviorTrace>>
  /** Perturbation kinds to apply (P1/P2/P3). */
  readonly perturbationKinds: readonly PerturbationKind[]
  /** Fault injection index. */
  readonly atIndex?: number
  /** Transient window length. */
  readonly transientWindow?: number
  /** The agent's recovery loop: maps a perturbed trace to a recovered trace. */
  readonly recover: (perturbed: BehaviorTrace) => BehaviorTrace
  /** Optional topology used only for a null-model comparison signal. */
  readonly topology?: Graph
  readonly numSwaps?: number
  readonly seed?: number
}

export interface CellResult {
  readonly taskDim: string
  readonly kind: PerturbationKind
  readonly prr: number
  readonly recoveryCost: number
}

export interface SteeringResult {
  readonly cells: readonly CellResult[]
  readonly meanPrr: number
}

export function runSteeringBenchmark(cfg: SteeringConfig): SteeringResult {
  const cells: CellResult[] = []
  for (const taskDim of Object.keys(cfg.referenceTraces)) {
    const reference = cfg.referenceTraces[taskDim]
    for (const kind of cfg.perturbationKinds) {
      const perturbed = applyPerturbation(reference, kind, {
        atIndex: cfg.atIndex,
        transientWindow: cfg.transientWindow,
      })
      const recovered = cfg.recover(perturbed)
      cells.push({
        taskDim,
        kind,
        prr: perturbationRecoveryRate(reference, perturbed, recovered),
        recoveryCost: recoveryCost(reference, perturbed, recovered),
      })
    }
  }
  const meanPrr = cells.length ? cells.reduce((s, c) => s + c.prr, 0) / cells.length : 0
  return { cells, meanPrr }
}

/** Optional null-model topology signal (degree-preserving baseline). */
export function nullModelTopology(cfg: SteeringConfig): Graph | null {
  if (!cfg.topology)
    return null
  return degreePreservingNull(cfg.topology, cfg.numSwaps ?? cfg.topology.edges.length, cfg.seed ?? 1)
}

// Keep mulberry32 referenced for callers that want a seeded RNG without importing randomization directly.
export { mulberry32 }
