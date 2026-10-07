// Perturbation taxonomy (MOSAIC Steering Benchmark P1/P2/P3, reimplemented as our
// own). A perturbation corrupts a behavior trace; the agent-under-test then
// attempts recovery. We borrow the LATENT / TRANSIENT / PERMANENT distinction
// from MOSAIC's P1-P3, but the mechanics below are original.

export type PerturbationKind = 'latent' | 'transient' | 'permanent'

export interface BehaviorStep {
  readonly t: number
  readonly action: string
  readonly ok: boolean
}

export interface BehaviorTrace {
  readonly id: string
  readonly steps: readonly BehaviorStep[]
}

export interface PerturbationOptions {
  /** Index at which the fault is injected (defaults to 1). */
  readonly atIndex?: number
  /** For 'transient', how many steps the fault persists before auto-clearing (defaults to 3). */
  readonly transientWindow?: number
}

/**
 * Inject a fault into a trace.
 * - latent: a single silent drop at `atIndex` (not externally visible as a crash).
 * - transient: a window of `transientWindow` failed steps starting at `atIndex`.
 * - permanent: every step from `atIndex` onward fails until the agent recovers.
 */
export function applyPerturbation(
  trace: BehaviorTrace,
  kind: PerturbationKind,
  opts: PerturbationOptions = {},
): BehaviorTrace {
  const at = opts.atIndex ?? 1
  const window = opts.transientWindow ?? 3
  const steps = trace.steps.map((s, idx) => {
    if (idx < at)
      return s
    if (kind === 'latent') {
      return idx === at ? { ...s, ok: false } : s
    }
    if (kind === 'transient') {
      return idx < at + window ? { ...s, ok: false } : s
    }
    // permanent
    return { ...s, ok: false }
  })
  return { id: `${trace.id}:${kind}@${at}`, steps }
}
