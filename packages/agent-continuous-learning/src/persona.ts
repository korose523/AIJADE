/**
 * Persona + affective state for the continuous-learning layer.
 *
 * Built from the four reference projects:
 * - `emotion_spirit` — a 13-dimension persona vector + PAD emotion + Big-Five
 *   derivation + a 6-dimension asymmetric intimacy model.
 * - `leuke` — tick-based endocrine (hormone) dynamics driving mood, voice rate
 *   and a "silence clock" (idle → rising longing / spontaneous monologue).
 * - `Openclaw` — the persona is a compact, token-cheap numeric matrix rather
 *   than prose, so `toContext()` stays small enough to inject every turn.
 * - `HY-Motion` — persona + endocrine drift is what turns feedback into
 *   behaviour change (see learning.ts), not a static label.
 *
 * Layers:
 * - `PersonaVector` — the 13 stable traits (0..1).
 * - `EndocrineState` — 5 tick-decaying hormones (0..1).
 * - `PADState` — Pleasure/Arousal/Dominance, derived from the above.
 * - `BigFive` — O/C/E/A/N, derived from the 13-dim vector (never hard-coded).
 * - `ThreeForceState` — natural/social/individual weights (sum 1).
 * - `IntimacyState` — 6 asymmetric relation dimensions (warmth/trust/...).
 * - `MoodProfile` — render-time projection (emoji, voice rate/pitch, style).
 */

import type { HormoneName, HormoneReaction, IntimacyName, IntimacyReaction, IntimacyRelaxation, PersonaDynamicsConfig, Relaxation, TraitName, TraitReaction } from './dynamics'

import {
  DEFAULT_DYNAMICS,

} from './dynamics'

export interface PersonaVector {
  openness: number
  warmth: number
  curiosity: number
  patience: number
  formality: number
  playfulness: number
  caution: number
  confidence: number
  empathy: number
  spontaneity: number
  diligence: number
  assertiveness: number
  stability: number
}

export interface EndocrineState {
  /** Reward / motivation. */
  dopamine: number
  /** Calm / well-being. */
  serotonin: number
  /** Stress. */
  cortisol: number
  /** Bonding / trust. */
  oxytocin: number
  /** Alertness / urgency. */
  adrenaline: number
}

/** Pleasure / Arousal / Dominance — the canonical emotion coordinates. */
export interface PADState {
  pleasure: number
  arousal: number
  dominance: number
}

/** Big-Five, always derived from {@link PersonaVector} (never hard-coded). */
export interface BigFive {
  O: number
  C: number
  E: number
  A: number
  N: number
}

/** Three-force dynamics: natural / social / individual (sum to 1). */
export interface ThreeForceState {
  natural: number
  social: number
  individual: number
}

/**
 * Six asymmetric intimacy dimensions (emotion_spirit). They are updated
 * independently per interaction and drift on idle — e.g. `longing` rises the
 * longer the user is silent, giving the desktop pet a "misses you" feel.
 */
export interface IntimacyState {
  warmth: number
  trust: number
  dependence: number
  security: number
  familiarity: number
  longing: number
}

export interface PersonaState {
  vector: PersonaVector
  endocrine: EndocrineState
  intimacy: IntimacyState
  updatedAt: number
}

/** Render-time projection of mood into UI/affective signals. */
export interface MoodProfile {
  /** Short label, e.g. "motivated". */
  label: string
  /** Emoji for the floating pet avatar. */
  emoji: string
  /** Speech rate multiplier (leuke voice_loop). */
  voiceRate: number
  /** Speech pitch multiplier. */
  voicePitch: number
  /** Speaking style hint. */
  style: string
}

export interface InteractionSignal {
  /** -1 (negative) .. +1 (positive). */
  valence: number
  /** 0 (calm) .. +1 (aroused/excited). */
  arousal: number
  /** Optional free-text event, used for context logging only. */
  event?: string
}

function clamp01(n: number): number {
  return Math.max(0, Math.min(1, n))
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n))
}

function meanRevert(current: number, baseline: number, rate: number): number {
  return current + (baseline - current) * rate
}

/**
 * Random source used when `drift.noiseSigma > 0`.
 *
 * Kept out of {@link PersonaDynamicsConfig} on purpose: the config must stay
 * JSON-serialisable so it can be fingerprinted and logged with every
 * observation. Experiments that need reproducible noise inject a seeded PRNG
 * here (e.g. `mulberry32(seed)`), which leaves the recorded config untouched.
 */
let rng: () => number = Math.random

/** Override the noise source. Pass `Math.random` to restore the default. */
export function setDynamicsRng(next: () => number): void {
  rng = next
}

/** Box–Muller transform: uniform [0,1) → standard normal. */
function gaussian(): number {
  let u = 0
  let v = 0
  while (u === 0)
    u = rng()
  while (v === 0)
    v = rng()
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v)
}

const VECTOR_DIMS: (keyof PersonaVector)[] = [
  'openness',
  'warmth',
  'curiosity',
  'patience',
  'formality',
  'playfulness',
  'caution',
  'confidence',
  'empathy',
  'spontaneity',
  'diligence',
  'assertiveness',
  'stability',
]

function createVector(seed = 0.5): PersonaVector {
  const v = {} as PersonaVector
  // Small deterministic-ish jitter so agents aren't identical.
  for (const dim of VECTOR_DIMS)
    v[dim] = clamp01(seed + (Math.random() - 0.5) * 0.1)
  return v
}

export function createIntimacyState(): IntimacyState {
  return {
    warmth: 0.3,
    trust: 0.3,
    dependence: 0.2,
    security: 0.4,
    familiarity: 0.5,
    longing: 0.2,
  }
}

export function createPersonaState(seed = 0.5): PersonaState {
  return {
    vector: createVector(seed),
    endocrine: {
      dopamine: 0.5,
      serotonin: 0.5,
      cortisol: 0.2,
      oxytocin: 0.4,
      adrenaline: 0.2,
    },
    intimacy: createIntimacyState(),
    updatedAt: Date.now(),
  }
}

/**
 * Apply a single interaction signal to hormones, persona and intimacy.
 *
 * The coefficients come from {@link PersonaDynamicsConfig} instead of being
 * hard-coded, so a study can sweep them. `config` is optional and defaults to
 * the original behaviour.
 */
export function applyInteraction(
  state: PersonaState,
  signal: InteractionSignal,
  config: PersonaDynamicsConfig = DEFAULT_DYNAMICS,
): PersonaState {
  const v = { ...state.vector }
  const e = { ...state.endocrine }
  const i = applyIntimacy(state.intimacy, signal, config)

  const val = clamp01((signal.valence + 1) / 2) // 0..1
  const aro = clamp01(signal.arousal)
  const gain = config.interactionGain
  const vN = config.valenceNeutral

  // Hormones react to valence/arousal.
  for (const entry of Object.entries(config.endocrine)) {
    const name = entry[0] as HormoneName
    const rxn = entry[1] as HormoneReaction
    const aN = rxn.arousalNeutral ?? 0
    e[name] = clamp01(e[name] + gain * ((rxn.valence ?? 0) * (val - vN) + (rxn.arousal ?? 0) * (aro - aN)))
  }

  // Persona shifts with the same signal (and with the hormone state just
  // updated above — the endocrine→persona coupling).
  for (const entry of Object.entries(config.traits)) {
    const name = entry[0] as TraitName
    const rxn = entry[1] as TraitReaction | undefined
    if (!rxn)
      continue
    let d = 0
    if (rxn.valence)
      d += rxn.valence * (val - (rxn.valenceNeutral ?? vN))
    if (rxn.arousal)
      d += rxn.arousal * (aro - (rxn.arousalNeutral ?? 0))
    if (rxn.hormone && rxn.hormoneGain)
      d += rxn.hormoneGain * (e[rxn.hormone] - (rxn.hormoneNeutral ?? 0))
    v[name] = clamp01(v[name] + gain * d)
  }

  return { vector: v, endocrine: e, intimacy: i, updatedAt: Date.now() }
}

/**
 * Time-based drift: hormones decay toward baseline and bias the persona vector
 * (cortisol raises caution / lowers patience; dopamine raises curiosity /
 * playfulness). Intimacy also drifts — `longing` creeps up the longer the user
 * is silent, while `security`/`dependence` relax toward baseline. Call
 * periodically (e.g. on a "silence clock" tick).
 */
export function drift(
  state: PersonaState,
  dtMs: number,
  config: PersonaDynamicsConfig = DEFAULT_DYNAMICS,
): PersonaState {
  const v = { ...state.vector }
  const e = { ...state.endocrine }
  const d = config.drift
  const i = driftIntimacy(state.intimacy, dtMs, config)

  const k = Math.min(1, dtMs / d.relaxationMs) // relaxation-window scaling
  for (const entry of Object.entries(d.endocrine)) {
    const name = entry[0] as HormoneName
    const rel = entry[1] as Relaxation
    e[name] = meanRevert(e[name], rel.baseline, k * rel.rate)
  }

  // Endocrine → persona coupling (the term ablation studies switch off).
  for (const entry of Object.entries(d.coupling)) {
    const name = entry[0] as TraitName
    const rxn = entry[1] as TraitReaction | undefined
    if (!rxn?.hormone || !rxn.hormoneGain)
      continue
    v[name] = clamp01(v[name] + rxn.hormoneGain * (e[rxn.hormone] - (rxn.hormoneNeutral ?? 0)))
  }

  if (d.noiseSigma > 0) {
    for (const dim of VECTOR_DIMS)
      v[dim] = clamp01(v[dim] + gaussian() * d.noiseSigma)
  }

  // Slow mean-reversion keeps the persona from wandering off.
  for (const dim of VECTOR_DIMS)
    v[dim] = meanRevert(v[dim], d.vectorBaseline, k * d.vectorMeanRevertRate)

  return { vector: v, endocrine: e, intimacy: i, updatedAt: Date.now() }
}

// ---------------------------------------------------------------------------
// PAD, Big-Five, three-force, intimacy, mood projections
// ---------------------------------------------------------------------------

/** Derive Pleasure/Arousal/Dominance from hormones + persona. */
export function toPAD(state: PersonaState): PADState {
  const e = state.endocrine
  const v = state.vector
  const pleasure = clamp01(0.5 + 0.35 * (e.serotonin - e.cortisol) + 0.15 * (e.dopamine - 0.5) + 0.1 * (v.warmth - 0.5))
  const arousal = clamp01(0.5 + 0.3 * (e.adrenaline - 0.3) + 0.25 * (e.dopamine - 0.5) - 0.2 * (e.serotonin - 0.5) + 0.1 * (v.curiosity - 0.5))
  const dominance = clamp01(0.5 + 0.3 * (v.confidence - 0.5) + 0.2 * (v.assertiveness - 0.5) + 0.1 * (v.caution - 0.5))
  return { pleasure, arousal, dominance }
}

/**
 * Big-Five derived from the 13-dim persona vector (emotion_spirit rule:
 * Big Five MUST be computed, never hard-coded). Each factor is the mean of
 * its contributing traits.
 */
export function toBigFive(vector: PersonaVector): BigFive {
  const O = (vector.openness + vector.curiosity + vector.spontaneity) / 3
  const C = (vector.diligence + vector.patience + vector.stability + vector.caution) / 4
  const E = (vector.warmth + vector.playfulness + vector.confidence + vector.assertiveness) / 4
  const A = (vector.warmth + vector.empathy + vector.patience) / 3
  // Neuroticism rises as stability/patience/confidence fall.
  const N = (1 - vector.stability) * 0.5 + (1 - vector.patience) * 0.3 + (1 - vector.confidence) * 0.2
  return { O: clamp01(O), C: clamp01(C), E: clamp01(E), A: clamp01(A), N: clamp01(N) }
}

/** Three-force dynamics (natural / social / individual), normalized to sum 1. */
export function toThreeForce(state: PersonaState): ThreeForceState {
  const v = state.vector
  const natural = 0.2 + ((v.stability + v.patience) / 2) * 0.3
  const social = 0.2 + ((v.warmth + v.empathy + v.playfulness) / 3) * 0.4
  const individual = 0.2 + ((v.assertiveness + v.curiosity + v.spontaneity) / 3) * 0.4
  const sum = natural + social + individual
  return {
    natural: natural / sum,
    social: social / sum,
    individual: individual / sum,
  }
}

/** Update the 6 intimacy dimensions from one interaction. */
export function applyIntimacy(
  state: IntimacyState,
  signal: InteractionSignal,
  config: PersonaDynamicsConfig = DEFAULT_DYNAMICS,
): IntimacyState {
  const i = { ...state }
  const val = clamp01((signal.valence + 1) / 2)
  const aro = clamp01(signal.arousal)
  const vN = config.valenceNeutral
  const gain = config.interactionGain

  for (const entry of Object.entries(config.intimacy)) {
    const name = entry[0] as IntimacyName
    const rxn = entry[1] as IntimacyReaction | undefined
    if (!rxn)
      continue
    let d = 0
    if (rxn.valence)
      d += rxn.valence * (val - vN)
    if (rxn.arousal)
      d += rxn.arousal * (aro - (rxn.arousalNeutral ?? 0))
    if (rxn.bias)
      d += rxn.bias
    if (rxn.unfamiliarity)
      d += rxn.unfamiliarity * (1 - i.familiarity)
    i[name] = clamp01(i[name] + gain * d)
  }
  return i
}

/** Slow idle drift of intimacy (longing creeps up; security relaxes). */
export function driftIntimacy(
  state: IntimacyState,
  dtMs: number,
  config: PersonaDynamicsConfig = DEFAULT_DYNAMICS,
): IntimacyState {
  const i = { ...state }
  const d = config.drift
  const k = Math.min(1, dtMs / d.intimacyRelaxationMs) // hourly scale
  for (const entry of Object.entries(d.intimacy)) {
    const name = entry[0] as IntimacyName
    const rel = entry[1] as IntimacyRelaxation | undefined
    if (!rel)
      continue
    if (rel.bias)
      i[name] = clamp01(i[name] + k * rel.bias)
    if (rel.baseline !== undefined && rel.rate !== undefined)
      i[name] = meanRevert(i[name], rel.baseline, k * rel.rate)
  }
  return i
}

const MOOD_EMOJI: Record<string, string> = {
  content: '😊',
  motivated: '🤩',
  stressed: '😣',
  connected: '🥰',
  alert: '😮',
  calm: '😌',
}

function dominantMood(e: EndocrineState): string {
  const entries: [string, number][] = [
    ['content', e.serotonin],
    ['motivated', e.dopamine],
    ['stressed', e.cortisol],
    ['connected', e.oxytocin],
    ['alert', e.adrenaline],
  ]
  entries.sort((a, b) => b[1] - a[1])
  return entries[0][0]
}

/** Project the full state into a compact UI/affective profile. */
export function toMoodProfile(state: PersonaState): MoodProfile {
  const e = state.endocrine
  const v = state.vector
  const pad = toPAD(state)
  const label = dominantMood(e)
  const emoji = MOOD_EMOJI[label] ?? '🙂'

  // leuke voice_loop: rate/pitch track hormones.
  const voiceRate = clamp(1 + 0.2 * (e.dopamine - 0.5) - 0.1 * (e.serotonin - 0.5) + 0.15 * (e.adrenaline - 0.3), 0.6, 1.6)
  const voicePitch = clamp(1 + 0.1 * (e.dopamine - 0.5) + 0.1 * (e.cortisol - 0.2), 0.7, 1.4)

  let style = 'calm'
  if (pad.arousal > 0.6)
    style = 'excited'
  else if (e.cortisol > 0.5)
    style = 'tense'
  else if (v.warmth > 0.6)
    style = 'warm'
  else if (v.playfulness > 0.6)
    style = 'playful'
  else if (v.confidence > 0.6)
    style = 'confident'

  return { label, emoji, voiceRate, voicePitch, style }
}

/** Render the persona as a compact prompt supplement (token-cheap). */
export function toContext(state: PersonaState): string {
  const v = state.vector
  const traits: string[] = []
  const push = (name: string, value: number, high: string, low: string) =>
    traits.push(`${name}:${value > 0.6 ? high : value < 0.4 ? low : 'balanced'}`)
  push('openness', v.openness, 'open', 'focused')
  push('warmth', v.warmth, 'warm', 'reserved')
  push('curiosity', v.curiosity, 'curious', 'steady')
  push('caution', v.caution, 'cautious', 'bold')
  push('playfulness', v.playfulness, 'playful', 'serious')
  push('formality', v.formality, 'formal', 'casual')

  const pad = toPAD(state)
  const mood = toMoodProfile(state)
  const big5 = toBigFive(v)
  const force = toThreeForce(state)
  const i = state.intimacy

  return [
    `Persona[${traits.join(', ')}]`,
    `mood=${mood.label}${mood.emoji} PAD(p:${e2(pad.pleasure)},a:${e2(pad.arousal)},d:${e2(pad.dominance)})`,
    `big5(O:${e2(big5.O)},C:${e2(big5.C)},E:${e2(big5.E)},A:${e2(big5.A)},N:${e2(big5.N)})`,
    `force(social:${e2(force.social)})`,
    `intimacy(warmth:${e2(i.warmth)},trust:${e2(i.trust)},familiar:${e2(i.familiarity)},longing:${e2(i.longing)})`,
  ].join(' ')
}

function e2(n: number): string {
  return n.toFixed(2)
}
