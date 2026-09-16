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

import type { AppliedParams, RenderAuditEntry } from './types'

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
 * Encode one channel value into a form that cannot collide across types.
 *
 * Numbers are emitted **without a tag** — deliberately, so that fingerprints
 * computed before this module accepted non-numeric channels stay bit-identical.
 * Strings and booleans get distinct tags, so the string `'0.5'` can never
 * collide with the number `0.5`, and the string `'true'` can never collide with
 * the boolean `true`.
 *
 * This encoder is a **cross-boundary contract**: `@proj-aijade/stage-ui` mirrors
 * it (it cannot import this package without dragging `node:fs` into a browser
 * bundle). Both sides pin the same literal vector in their tests, so a change to
 * one side without the other goes red.
 */
function formatScalar(v: number | string | boolean): string {
  if (typeof v === 'number')
    return formatNumber(v)
  if (typeof v === 'boolean')
    return v ? 'b:1' : 'b:0'
  return `s:${v}`
}

/**
 * Order-independent, precision-deterministic fingerprint of a `channel→value` map.
 *
 * - Keys are sorted, so the output is identical for any insertion order.
 * - Values are normalised to fixed precision, so `0.1 + 0.2` and `0.3` collapse
 *   to the same fingerprint (float noise never splits two renders that are
 *   genuinely identical).
 * - Non-numeric channels are tag-encoded (see {@link formatScalar}) so the three
 *   real channel kinds — numeric / categorical / switch — stay distinguishable.
 * - An empty map yields the stable empty string `''`, never `undefined`/`NaN`.
 *   ⚠️ Callers that require a *non-empty* fingerprint (e.g. the v9
 *   `lpm.render_ready` payload, whose `applied_params_hash` is `.min(1)`) must
 *   treat `''` as "nothing was written" and **not emit** — see
 *   `memory-biomimetic`'s `buildLpmRenderReadyEvent`.
 */
export function fingerprintAppliedParams(params: AppliedParams): string {
  const parts = Object.entries(params)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${k}=${formatScalar(v)}`)
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
