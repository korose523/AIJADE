/**
 * Parameter-sweep utilities for Gap #2.
 *
 * Context: the affective-dynamics models this project's persona layer is
 * descended from (Garcia et al., *Royal Society Open Science*, 2016; Pellert
 * et al., *EPJ Data Science*, 2020; the Affective Ising Model of
 * Vanhasbroeck et al., *Affective Science*, 2022) fitted their parameters
 * against **human self-reported emotion time series**. Those fitted values are
 * then reused — without revalidation — whenever someone wires the same model
 * into an agent that *drives text generation*.
 *
 * Nobody has asked: which of these parameters actually matter once the output
 * is language, not a mood rating? That is a parameter-sensitivity question, and
 * this module provides the machinery to run it.
 *
 * Note the distinction from a module ablation: CTEM/Auri (CHI '26) removed
 * whole modules (BGI / AdI / ESU) over 21 days. Removing a module is a
 * discrete* manipulation; sweeping relaxation time constants is a *continuous*
 * one. The continuous question is the one still open.
 */

import type { DynamicsParameters } from './types'

/** Numeric axes that can be swept. */
export type SweepAxis = 'relaxationMs' | 'noiseSigma' | 'interactionGain' | 'tickIntervalMs'

/** One point in a parameter sweep, i.e. one experimental cell. */
export interface SweepPoint {
  /** Short label, e.g. `relax-50pct`. Used as the condition name. */
  name: string
  parameters: DynamicsParameters
}

/**
 * Fingerprint a parameter set deterministically.
 *
 * Nested `baseline` / `hormoneCoupling` maps are key-sorted first, so two
 * semantically identical objects always hash the same regardless of how they
 * were constructed.
 */
export function fingerprintParameters(params: DynamicsParameters): string {
  const parts: string[] = []

  for (const key of ['relaxationMs', 'noiseSigma', 'interactionGain', 'tickIntervalMs'] as const) {
    const v = params[key]
    if (v !== undefined)
      parts.push(`${key}=${round(v)}`)
  }

  if (params.baseline) {
    const inner = Object.entries(params.baseline)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([k, v]) => `${k}=${round(v ?? 0)}`)
      .join(',')
    parts.push(`baseline{${inner}}`)
  }

  if (params.hormoneCoupling) {
    const inner = Object.entries(params.hormoneCoupling)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([k, v]) => `${k}=${round(v ?? 0)}`)
      .join(',')
    parts.push(`coupling{${inner}}`)
  }

  return parts.join('|')
}

function round(n: number): string {
  // 6 significant decimals is far beyond any behavioural effect size while
  // still absorbing float noise from sweep arithmetic.
  return Number(n.toFixed(6)).toString()
}

/**
 * Build a one-dimensional sweep: vary a single axis around a centre value,
 * holding everything else fixed.
 *
 * One-at-a-time (OAT) is the right first design here: with six knobs a full
 * factorial is unaffordable, and OAT gives you the per-parameter main effect,
 * which is exactly "which parameters matter".
 */
export function sweepAxis(
  axis: SweepAxis,
  values: readonly number[],
  base: DynamicsParameters = {},
): SweepPoint[] {
  return values.map((v) => {
    const parameters: DynamicsParameters = { ...base, [axis]: v }
    return {
      name: `${AXIS_SLUG[axis]}-${formatValue(v)}`,
      parameters,
    }
  })
}

/**
 * Build a multi-dimensional grid.
 *
 * Use sparingly — the cell count is the product of all axis lengths. Two axes
 * at 3 levels each is 9 cells and lets you see an interaction; three axes at 4
 * levels is 64 cells and probably too many for a user study.
 */
export function sweepGrid(
  axes: Partial<Record<SweepAxis, readonly number[]>>,
  base: DynamicsParameters = {},
): SweepPoint[] {
  const entries = Object.entries(axes) as [SweepAxis, readonly number[]][]
  if (entries.length === 0)
    return [{ name: 'base', parameters: { ...base } }]

  let combos: DynamicsParameters[] = [{ ...base }]
  for (const [axis, values] of entries) {
    const next: DynamicsParameters[] = []
    for (const combo of combos) {
      for (const v of values)
        next.push({ ...combo, [axis]: v })
    }
    combos = next
  }

  return combos.map((parameters) => {
    const label = entries
      .map(([axis]) => `${AXIS_SLUG[axis]}-${formatValue(parameters[axis] ?? 0)}`)
      .join('_')
    return { name: label, parameters }
  })
}

const AXIS_SLUG: Record<SweepAxis, string> = {
  relaxationMs: 'relax',
  noiseSigma: 'noise',
  interactionGain: 'gain',
  tickIntervalMs: 'tick',
}

function formatValue(v: number): string {
  if (Number.isInteger(v))
    return String(v)
  return String(Number(v.toFixed(4)))
}

/**
 * A sensible default OAT sweep over the relaxation time constant.
 *
 * Relaxation time is the first knob to sweep because it is the one the classic
 * literature has a firm empirical grip on (Kuppens et al., *Cognition &
 * Emotion*, 2010, measured emotional persistence/inertia in humans) and
 * therefore the one whose *transferred* value is most questionable when the
 * consumer is an LLM rather than a human reporting a mood.
 */
export function defaultRelaxationSweep(
  centreMs: number,
  base: DynamicsParameters = {},
): SweepPoint[] {
  return sweepAxis('relaxationMs', [
    centreMs * 0.25,
    centreMs * 0.5,
    centreMs,
    centreMs * 2,
    centreMs * 4,
  ], base)
}
