/**
 * Tunable parameters of the affective dynamics.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * Every coefficient used to live inline as a magic number in `persona.ts`.
 * That made the dynamics impossible to sweep, and — more importantly —
 * impossible to *report*: a paper that says "we used a decay of 0.3" is
 * unreviewable if 0.3 is buried in a source file nobody can set.
 *
 * The literature (Garcia et al., Royal Society Open Science 2016; Pellert et
 * al., EPJ Data Science 2020; the Affective Ising Model) fitted these
 * parameters against **human self-reported emotion traces**. Nobody has
 * validated them for the purpose of *driving LLM generation*. Answering that
 * requires the parameters to be (a) settable, (b) recorded with every
 * observation, and (c) sweepable. This module provides (a);
 * `@proj-aijade/research-telemetry` provides (b) and (c).
 *
 * BACKWARD COMPATIBILITY
 * ----------------------
 * `DEFAULT_DYNAMICS` reproduces the original hard-coded behaviour bit for bit.
 * Every function in `persona.ts` keeps working when the config argument is
 * omitted, so existing callers and tests are unaffected.
 */

// ---------------------------------------------------------------------------
// Interaction-driven update (`applyInteraction` / `applyIntimacy`)
// ---------------------------------------------------------------------------

/** Per-hormone response to a normalized valence / arousal signal. */
export interface HormoneReaction {
  /** Multiplier on `(valence01 - valenceNeutral)`. */
  valence?: number
  /** Multiplier on `(arousal - arousalNeutral)`. */
  arousal?: number
  /** Arousal reference point (default 0). */
  arousalNeutral?: number
}

export type HormoneName = 'dopamine' | 'serotonin' | 'cortisol' | 'oxytocin' | 'adrenaline'

/**
 * Per-trait response. A trait can be driven by valence, arousal, and/or the
 * current endocrine state — the last of which is the "hormone → persona
 * coupling" that ablation studies switch off.
 */
export interface TraitReaction {
  /** Multiplier on `(valence01 - valenceNeutral)`. */
  valence?: number
  /** Valence reference point (default 0.5, i.e. neutral). */
  valenceNeutral?: number
  /** Multiplier on `(arousal - arousalNeutral)`. */
  arousal?: number
  /** Arousal reference point (default 0). */
  arousalNeutral?: number
  /** Multiplier on `(endocrine[hormone] - hormoneNeutral)`. */
  hormone?: HormoneName
  hormoneNeutral?: number
  hormoneGain?: number
}

export type TraitName
  = | 'openness' | 'warmth' | 'curiosity' | 'patience' | 'formality' | 'playfulness'
    | 'caution' | 'confidence' | 'empathy' | 'spontaneity' | 'diligence'
    | 'assertiveness' | 'stability'

/** Per-dimension intimacy response. */
export interface IntimacyReaction {
  /** Multiplier on `(valence01 - valenceNeutral)`. */
  valence?: number
  /** Multiplier on `(arousal - arousalNeutral)`. */
  arousal?: number
  arousalNeutral?: number
  /** Constant drift applied every interaction regardless of the signal. */
  bias?: number
  /** Multiplier on `(1 - familiarity)` — the "distance grows longing" term. */
  unfamiliarity?: number
}

export type IntimacyName = 'warmth' | 'trust' | 'dependence' | 'security' | 'familiarity' | 'longing'

// ---------------------------------------------------------------------------
// Time-based drift (`drift` / `driftIntimacy`)
// ---------------------------------------------------------------------------

/** Mean-reversion target + rate for one dimension. */
export interface Relaxation {
  /** Value the dimension reverts toward. */
  baseline: number
  /** Reversion fraction per full relaxation window. */
  rate: number
}

/**
 * Intimacy drift for one dimension. Unlike {@link Relaxation}, both fields are
 * optional: `longing` has a constant `bias` but no reversion target, because it
 * only creeps upward while the user is away.
 */
export interface IntimacyRelaxation {
  /** Constant delta per full window (independent of the current value). */
  bias?: number
  /** Value the dimension reverts toward. Omit to disable reversion. */
  baseline?: number
  /** Reversion fraction per full window. Omit to disable reversion. */
  rate?: number
}

export interface DriftConfig {
  /**
   * Relaxation time constant in ms — the window over which a full reversion
   * step is applied. `k = min(1, dtMs / relaxationMs)` scales every rate.
   * Default 600_000 (10 min) for endocrine, matching the original code.
   */
  relaxationMs: number
  /** Per-hormone reversion. */
  endocrine: Record<HormoneName, Relaxation>
  /** Hormone → persona coupling applied inside `drift`. */
  coupling: Partial<Record<TraitName, TraitReaction>>
  /** Slow whole-vector mean reversion, keeping the persona from wandering. */
  vectorBaseline: number
  vectorMeanRevertRate: number
  /** Intimacy drift window (default 3_600_000, hourly). */
  intimacyRelaxationMs: number
  /**
   * Per-dimension intimacy drift. `baseline`/`rate` are optional: omitting them
   * means "no mean-reversion for this dimension, only the constant `bias`"
   * (e.g. `longing` only ever creeps upward while the user is away).
   */
  intimacy: Partial<Record<IntimacyName, IntimacyRelaxation>>
  /**
   * Per-tick Gaussian noise intensity (σ), applied to the persona vector
   * before clamping. Default 0 — deterministic, which is what a controlled
   * experiment needs. Raise it to model affect stochasticity.
   */
  noiseSigma: number
}

// ---------------------------------------------------------------------------
// Top-level config
// ---------------------------------------------------------------------------

export interface PersonaDynamicsConfig {
  /** Reference point for normalized valence (0..1 space). Default 0.5. */
  valenceNeutral: number
  /** Interaction-driven hormone reactions. */
  endocrine: Record<HormoneName, HormoneReaction>
  /** Interaction-driven persona-trait reactions. */
  traits: Partial<Record<TraitName, TraitReaction>>
  /** Interaction-driven intimacy reactions. */
  intimacy: Partial<Record<IntimacyName, IntimacyReaction>>
  /** Time-based drift. */
  drift: DriftConfig
  /**
   * Global multiplier on the interaction-driven update. 0 disables
   * interaction-driven learning entirely (time drift still applies) — this is
   * the cleanest ablation of "does interaction actually shape the persona?".
   */
  interactionGain: number
}

/**
 * The original hard-coded behaviour, expressed as data.
 *
 * Derived mechanically from the pre-refactor `persona.ts`: `cortisol` uses a
 * negative valence gain because the original read `(0.5 - val) * 0.25`, and
 * `patience`/`stability` use negative gains for the same reason.
 */
export const DEFAULT_DYNAMICS: PersonaDynamicsConfig = {
  valenceNeutral: 0.5,
  endocrine: {
    dopamine: { valence: 0.3 },
    serotonin: { valence: 0.15 },
    cortisol: { valence: -0.25, arousal: 0.1 },
    oxytocin: { valence: 0.2 },
    adrenaline: { arousal: 0.3, arousalNeutral: 0.3 },
  },
  traits: {
    warmth: { valence: 0.1 },
    empathy: { valence: 0.08 },
    curiosity: { arousal: 0.06 },
    playfulness: { valence: 0.08, valenceNeutral: 0.3, arousal: 0.04 },
    patience: { hormone: 'cortisol', hormoneNeutral: 0.5, hormoneGain: -0.05 },
    caution: { hormone: 'cortisol', hormoneNeutral: 0.3, hormoneGain: 0.08 },
    confidence: { valence: 0.06 },
    assertiveness: { valence: 0.05, valenceNeutral: 0.4, arousal: 0.03 },
    stability: { arousal: -0.04, arousalNeutral: 0.5 },
  },
  intimacy: {
    warmth: { valence: 0.1 },
    trust: { valence: 0.08, bias: 0.01 },
    familiarity: { bias: 0.03 },
    security: { valence: 0.05, arousal: 0.02, arousalNeutral: 0.5 },
    dependence: { valence: 0.04 },
    longing: { bias: -0.02, unfamiliarity: 0.01 },
  },
  drift: {
    relaxationMs: 600_000,
    endocrine: {
      dopamine: { baseline: 0.5, rate: 0.3 },
      serotonin: { baseline: 0.5, rate: 0.2 },
      cortisol: { baseline: 0.2, rate: 0.4 },
      oxytocin: { baseline: 0.4, rate: 0.2 },
      adrenaline: { baseline: 0.2, rate: 0.5 },
    },
    coupling: {
      caution: { hormone: 'cortisol', hormoneNeutral: 0.3, hormoneGain: 0.02 },
      patience: { hormone: 'cortisol', hormoneNeutral: 0.3, hormoneGain: -0.02 },
      curiosity: { hormone: 'dopamine', hormoneNeutral: 0.5, hormoneGain: 0.02 },
      playfulness: { hormone: 'dopamine', hormoneNeutral: 0.5, hormoneGain: 0.02 },
    },
    vectorBaseline: 0.5,
    vectorMeanRevertRate: 0.05,
    intimacyRelaxationMs: 3_600_000,
    intimacy: {
      longing: { bias: 0.02 },
      security: { baseline: 0.4, rate: 0.1 },
      dependence: { baseline: 0.2, rate: 0.05 },
    },
    noiseSigma: 0,
  },
  interactionGain: 1,
}

// ---------------------------------------------------------------------------
// Merging & helpers
// ---------------------------------------------------------------------------

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/** Recursively merge `patch` into `base`, ignoring `undefined` values. */
function deepMerge<T>(base: T, patch: unknown): T {
  if (patch === undefined || patch === null)
    return base
  if (!isPlainObject(patch) || !isPlainObject(base))
    return patch as T
  const out: Record<string, unknown> = { ...base }
  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined)
      continue
    out[key] = deepMerge(out[key], value)
  }
  return out as T
}

/**
 * Build a full config from a partial override.
 *
 * Researchers pass only the knobs they are sweeping; everything else keeps the
 * validated default.
 */
export function resolveDynamics(override?: Partial<PersonaDynamicsConfig>): PersonaDynamicsConfig {
  return deepMerge(DEFAULT_DYNAMICS, override)
}

/**
 * A stable, human-readable fingerprint of a config — used to group replicates
 * of the same parameter point across participants and reruns.
 */
export function fingerprintDynamics(config: PersonaDynamicsConfig): string {
  return JSON.stringify(config, (_key, value) =>
    typeof value === 'number' ? Math.round(value * 1e6) / 1e6 : value)
}
