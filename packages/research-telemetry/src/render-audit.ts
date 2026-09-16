/**
 * Deterministic auditing of *what parameters were actually written to a render*.
 *
 * This is the concrete landing spot for the design doc's `applied_params_hash`
 * (see `RenderAuditEntry` in `./types`): a render is only reproducible if we
 * record the exact channel→value map that reached the model, not just the
 * intended parameters. The fingerprinting here follows the repository's house
 * rule established by `fingerprintConfig()` / `fingerprintParameters()`:
 * **synchronous, key-order-independent sorted `key:value` join — never
 * `JSON.stringify`**.
 *
 * This module stays dependency-free (it only imports a *type*), consistent with
 * the rest of `@proj-aijade/research-telemetry`, so it can be imported from any
 * runtime.
 */

import type { RenderAuditEntry } from './types'

/**
 * Fixed-precision formatter, mirroring the *private* `round()` in `./sweep`.
 *
 * We intentionally do **not** import or re-export `sweep`'s `round()`: it is
 * deliberately not part of that module's public surface, and widening the export
 * surface just to share a four-line helper would be the wrong trade. Keeping the
 * formatter local here keeps `render-audit` self-contained and dependency-free.
 */
function formatNumber(n: number): string {
  // 6 significant decimals — far beyond any behavioural effect size, while still
  // absorbing the float noise that creeps in from arithmetic along the render path.
  return Number(n.toFixed(6)).toString()
}

/**
 * Order-independent, precision-deterministic fingerprint of a `channel→value` map.
 *
 * - Keys are sorted, so the output is identical for any insertion order.
 * - Values are normalised to fixed precision, so `0.1 + 0.2` and `0.3` collapse
 *   to the same fingerprint (float noise never splits two renders that are
 *   genuinely identical).
 * - An empty map yields the stable empty string `''`, never `undefined`/`NaN`.
 */
export function fingerprintAppliedParams(params: Record<string, number>): string {
  const parts = Object.entries(params)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${k}=${formatNumber(v)}`)
  return parts.join('|')
}

/**
 * Pure constructor for a render audit entry.
 *
 * Fills `appliedParamsHash` from the supplied `appliedParams` via
 * `fingerprintAppliedParams()`, so callers only ever provide the actual params
 * and never a hand-computed (and possibly mismatched) hash. Everything else is
 * passed through unchanged.
 */
export function buildRenderAuditEntry(
  input: Omit<RenderAuditEntry, 'appliedParamsHash'>,
): RenderAuditEntry {
  return {
    ...input,
    appliedParamsHash: fingerprintAppliedParams(input.appliedParams),
  }
}
