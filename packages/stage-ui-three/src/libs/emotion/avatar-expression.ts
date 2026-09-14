/**
 * avatar-expression — reusable expressiveness helpers for AIJADE's VRM avatar.
 *
 * Distilled from companion / emotion projects researched for this integration:
 *  - astrbot_plugin_emotion_spirit: PAD (Pleasure-Arousal-Dominance) vector ->
 *    expression weights (here collapsed onto VRM preset weights).
 *  - AkaneCompanionLab EmotionMapper: arbitrary LLM emotion label -> a known
 *    resource via an alias table with multi-level fallback.
 *  - leuke silence_loop: a "silence clock" + refractory cooldown that triggers
 *    spontaneous reactions only after the user has been quiet for a while.
 *  - LPM 1.0 (LivePortrait): three real-time states (listen / speak / silence)
 *    + gaze markers drive blinking/gaze "from performance cues" rather than
 *    pure random timers.
 *
 * Everything here is pure / framework-free so it can be unit-tested and reused
 * by any VRM runtime (AIJADE stage, chat widget, etc.).
 */

import type { PerformanceEmotion } from '@proj-aijade/memory-pgvector/performance'

/** VRM's built-in expression presets we drive. */
export type VrmExpressionPreset
  = | 'neutral'
    | 'happy'
    | 'angry'
    | 'sad'
    | 'relaxed'
    | 'surprised'

export const VRM_PRESETS: VrmExpressionPreset[] = [
  'neutral',
  'happy',
  'angry',
  'sad',
  'relaxed',
  'surprised',
]

/**
 * Alias table: many natural-language emotion labels an LLM might emit ->
 * a single canonical VRM preset. Add freely; lookups are case/space-insensitive.
 */
export const EMOTION_ALIASES: Record<string, VrmExpressionPreset> = {
  // happy
  happy: 'happy',
  joy: 'happy',
  joyful: 'happy',
  excited: 'happy',
  excitedly: 'happy',
  delight: 'happy',
  glad: 'happy',
  cheerful: 'happy',
  amused: 'happy',
  pride: 'happy',
  love: 'happy',
  loving: 'happy',
  adore: 'happy',
  affection: 'happy',
  // angry
  angry: 'angry',
  mad: 'angry',
  rage: 'angry',
  furious: 'angry',
  annoy: 'angry',
  annoyed: 'angry',
  irritate: 'angry',
  frustrated: 'angry',
  frustration: 'angry',
  // sad
  sad: 'sad',
  upset: 'sad',
  unhappy: 'sad',
  cry: 'sad',
  crying: 'sad',
  sorrow: 'sad',
  grief: 'sad',
  disappointed: 'sad',
  lonely: 'sad',
  hurt: 'sad',
  // relaxed
  calm: 'relaxed',
  relaxed: 'relaxed',
  content: 'relaxed',
  peaceful: 'relaxed',
  chill: 'relaxed',
  serene: 'relaxed',
  sleepy: 'relaxed',
  tired: 'relaxed',
  think: 'relaxed',
  thinking: 'relaxed',
  ponder: 'relaxed',
  focus: 'relaxed',
  // surprised
  surprised: 'surprised',
  shock: 'surprised',
  shocked: 'surprised',
  wow: 'surprised',
  amazed: 'surprised',
  startle: 'surprised',
  gasp: 'surprised',
  confuse: 'surprised',
  confused: 'surprised',
  curious: 'surprised',
  wonder: 'surprised',
}

function clamp01(x: number): number {
  return Math.max(0, Math.min(1, x))
}

/**
 * Normalize an arbitrary emotion label to a known VRM preset.
 * Returns 'neutral' when nothing matches (safe fallback — never throws).
 */
export function normalizeEmotionLabel(raw: string | null | undefined): VrmExpressionPreset {
  if (!raw)
    return 'neutral'
  const key = raw.trim().toLowerCase().replace(/[\s_-]+/g, '')
  if ((VRM_PRESETS as string[]).includes(key))
    return key as VrmExpressionPreset
  return EMOTION_ALIASES[key] ?? 'neutral'
}

export interface PAD {
  /** Pleasure: -1 (unpleasant) .. +1 (pleasant). */
  pleasure: number
  /** Arousal: -1 (calm) .. +1 (activated). */
  arousal: number
  /** Dominance: -1 (submissive) .. +1 (dominant). */
  dominance: number
}

/**
 * Map a continuous PAD vector onto a single dominant VRM preset + intensity.
 * Deterministic and bounded (intensity in [0,1]); the avatar's expression
 * manager applies it as a weight, giving smooth (not binary) facial reactions.
 */
export function padToPreset(pad: PAD): { preset: VrmExpressionPreset, intensity: number } {
  const p = Math.max(-1, Math.min(1, pad.pleasure))
  const a = Math.max(-1, Math.min(1, pad.arousal))
  const d = Math.max(-1, Math.min(1, pad.dominance))

  const weights: Record<VrmExpressionPreset, number> = {
    neutral: 0.15, // small resting bias so the face is never fully dead
    happy: Math.max(0, p),
    sad: Math.max(0, -p),
    surprised: Math.max(0, a + Math.max(0, -d) * 0.3),
    angry: Math.max(0, d * Math.max(0, p)), // dominant + pleasant -> assertive (mapped to angry-ish assert)
    relaxed: Math.max(0, -a) * Math.max(0, p + 0.2),
  }
  // 'angry' channel above is really "assertive"; fold very high dominance into happy/relaxed
  weights.angry = Math.max(0, d) * Math.max(0, -p) * 0.8

  let best: VrmExpressionPreset = 'neutral'
  let bestW = weights.neutral
  for (const k of VRM_PRESETS) {
    if (weights[k] > bestW) {
      bestW = weights[k]
      best = k
    }
  }
  return { preset: best, intensity: clamp01(bestW) }
}

/**
 * Per-emotion expression intensity. Applying expressions at <1 leaves headroom
 * so the avatar never looks "maxed out / too raw" (the #590 "smiles too much"
 * problem). Streamed performance cues pass this through to `useVRMEmote`.
 */
export const EMOTION_INTENSITY: Record<PerformanceEmotion, number> = {
  neutral: 0.5,
  happy: 0.8,
  sad: 0.7,
  angry: 0.7,
  surprised: 0.7,
  thinking: 0.6,
  loving: 0.85,
  calm: 0.55,
  worried: 0.65,
  // ── LPM-aligned listener/expressive extensions ──
  amused: 0.8,
  curious: 0.7,
  embarrassed: 0.6,
  grateful: 0.85,
  tender: 0.8,
  proud: 0.8,
}

export function emotionIntensity(emotion: PerformanceEmotion): number {
  return EMOTION_INTENSITY[emotion] ?? 0.7
}

/**
 * Frame-rate-independent exponential smoothing toward a target.
 * `tau` is the time constant (seconds): ~63% of the gap closes in `tau`,
 * ~95% in 3·tau. Used by `useVRMEmote` so re-targeting an emotion mid-flight
 * redirects smoothly instead of snapping (kills streaming-token jitter).
 */
export function smoothTowards(current: number, target: number, dt: number, tau: number): number {
  if (tau <= 0)
    return target
  const a = 1 - Math.exp(-dt / tau)
  return current + (target - current) * a
}

/**
 * Map a performance `gaze` marker to a look-at target offset (meters) around a
 * base point. Pure + testable; the Vue layer applies it to `vrm.lookAt.target`.
 * Anything not a cardinal direction is treated as `center` (no offset).
 */
export function gazeDirectionToOffset(dir: string | null | undefined, amount = 0.35): { x: number, y: number, z: number } {
  switch ((dir || 'center').trim().toLowerCase()) {
    case 'left': return { x: -amount, y: 0, z: 0 }
    case 'right': return { x: amount, y: 0, z: 0 }
    case 'up': return { x: 0, y: amount, z: 0 }
    case 'down': return { x: 0, y: -amount, z: 0 }
    default: return { x: 0, y: 0, z: 0 }
  }
}

/**
 * Minimal persona projection the avatar's *autonomous* (idle) behavior reacts
 * to. It is a structural subset of `@proj-aijade/agent-continuous-learning`'s
 * `PersonaState`, so the live persona can be passed straight through without
 * stage-ui-three taking a dependency on that package (a superset is always
 * assignable to a subset in TS).
 */
export interface PersonaSignal {
  intimacy: { warmth: number, trust: number, familiarity: number, longing: number }
  endocrine: { dopamine: number, serotonin: number, cortisol: number, oxytocin: number, adrenaline: number }
  vector: { playfulness: number, spontaneity: number }
}

export interface IdleBias {
  /** Gesture pool biased by the current persona (replaces the default). */
  pool: string[]
  /** Subtle emotion the avatar drifts toward while musing (low intensity). */
  emotion: PerformanceEmotion | null
  /** Gaze direction the avatar leans toward while musing. */
  gazeBias: string | null
  /** Blink-cadence multiplier (1 = natural; >1 faster, <1 slower). */
  blinkRateScale: number
}

/**
 * Map a persona snapshot onto autonomous-idle behavior bias. Pure + unit-tested.
 * This is the "self-driven agent" core (Neuro-Sama / z-waif style): the avatar's
 * spontaneous micro-behaviors during user silence reflect its *internal* state —
 * relationship closeness, hormones, traits — rather than a fixed random pool.
 *
 *  - warm / trusting / familiar + high oxytocin  → friendly pool (wave / nod / agree)
 *  - low familiarity or low trust                → cautious pool (shrug / think / point)
 *  - high cortisol / adrenaline                 → fidgety (think / point / surprised)
 *  - high longing                               → wistful (think + gaze up)
 *  - high dopamine + oxytocin                   → happy drift; high cortisol → worried
 *  - high adrenaline                            → faster blink; high serotonin → slower
 */
export function personaToIdleBias(p: PersonaSignal): IdleBias {
  const { warmth, trust, familiarity, longing } = p.intimacy
  const { dopamine, serotonin, cortisol, oxytocin, adrenaline } = p.endocrine
  const { playfulness, spontaneity } = p.vector

  const friendly = (warmth + trust + familiarity + oxytocin) / 4
  const cautious = (1 - familiarity) * 0.6 + (1 - trust) * 0.4
  const fidgety = (cortisol + adrenaline) / 2

  let pool: string[]
  if (friendly > 0.6)
    pool = ['wave', 'nod', 'agree', 'think']
  else if (cautious > 0.5)
    pool = ['shrug', 'think', 'point']
  else
    pool = ['think', 'nod', 'shrug']

  if (fidgety > 0.55)
    pool = [...new Set([...pool, 'think', 'point', 'surprised'])]
  if (playfulness > 0.6 || spontaneity > 0.6)
    pool = [...new Set([...pool, 'wave', 'nod'])]

  let emotion: PerformanceEmotion | null = null
  if (dopamine > 0.6 && oxytocin > 0.5)
    emotion = 'happy'
  else if (cortisol > 0.6)
    emotion = 'worried'
  else if (serotonin > 0.6)
    emotion = 'calm'

  let gazeBias: string | null = null
  if (longing > 0.6)
    gazeBias = 'up'
  else if (trust > 0.6)
    gazeBias = null // holds eye contact (center)
  else if (familiarity < 0.4)
    gazeBias = 'down' // shy

  const blinkRateScale = Math.max(0.5, Math.min(1.6, 0.85 + adrenaline * 0.5 - serotonin * 0.3))

  return {
    pool: pool.length ? pool : ['think', 'nod', 'shrug'],
    emotion,
    gazeBias,
    blinkRateScale,
  }
}

export interface IdleSpontaneousOptions {
  /** Gesture / emote names that may fire when the user goes quiet. */
  pool?: string[]
  /** Silence duration before the first spontaneous reaction. */
  idleThresholdMs?: number
  /** Refractory window after a trigger (prevents spamming). */
  cooldownMs?: number
}

/**
 * Silence-clock with refractory cooldown (from leuke's silence_loop).
 * Call {@link tick} every frame with the current time and whether the user is
 * silent; it fires `trigger(gesture)` only after a quiet stretch and then waits
 * out the cooldown. Reset it when the user becomes active again.
 */
export class IdleSpontaneousController {
  private silenceStart: number | null = null
  private lastTrigger = -Infinity
  private pool: string[]
  private readonly threshold: number
  private readonly cooldown: number

  constructor(opts: IdleSpontaneousOptions = {}) {
    this.pool = opts.pool && opts.pool.length
      ? opts.pool
      : ['think', 'nod', 'shrug']
    this.threshold = opts.idleThresholdMs ?? 4500
    this.cooldown = opts.cooldownMs ?? 9000
  }

  tick(now: number, isSilence: boolean, trigger: (gesture: string) => void): void {
    if (!isSilence) {
      this.silenceStart = null
      return
    }
    this.silenceStart ??= now
    const elapsed = now - this.silenceStart
    const sinceTrigger = now - this.lastTrigger
    if (elapsed >= this.threshold && sinceTrigger >= this.cooldown) {
      this.lastTrigger = now
      const g = this.pool[Math.floor(Math.random() * this.pool.length)]
      trigger(g)
    }
  }

  reset(): void {
    this.silenceStart = null
    this.lastTrigger = -Infinity
  }

  /** Update the candidate gesture pool (e.g. as the persona state evolves). */
  setPool(pool: string[]): void {
    if (pool && pool.length)
      this.pool = pool
  }
}
