import type { PerformanceMarker, PerformanceMarkerKey } from './markers'

import { parsePerformanceMarkers } from './markers'

/**
 * Performance state machine for AIJADE, directly mirroring **LPM 1.0**'s runtime
 * states and multimodal controls (arXiv:2604.07823):
 *
 * - `listen`  — user is talking; the avatar should *listen* (nod, glance,
 *               micro-smile, head-tilt). LPM stresses that listening is ~half of
 *               all conversation and must carry rich non-verbal behavior, not a
 *               frozen neutral face. We drive that through {@link tick} reaction
 *               scheduling + the dual-stream {@link feedUserAudio} arousal cue.
 * - `speak`   — assistant is generating; avatar should speak. Entered on the
 *               **first streamed token** (not after the full reply is ready) to
 *               close the "artificial silence" gap (StreamPet / BV1yT96mE6t).
 * - `silence` — turn over, idle-but-alive (LPM `idle`). We use this window for
 *               long-horizon *anti-drift*: the emotion relaxes back toward a
 *               stable baseline so the character never gets stuck in a state
 *               (LPM's autoregressive identity drift / DPO "emotional flatness").
 *
 * On top of the tristate, the director tracks structured cues the avatar/TTS can
 * consume: emotion, gesture, gaze, music, a running relationship delta, and a
 * live user-audio arousal (the LPM "listen audio branch"). The `<|...|>` markers
 * override lexicon guesses; once an explicit emotion marker arrives the lexicon
 * is locked so the model stays in character.
 */
export type PerformanceEmotion
  = | 'neutral'
    | 'happy'
    | 'sad'
    | 'angry'
    | 'surprised'
    | 'thinking'
    | 'loving'
    | 'calm'
    | 'worried'
    // ── LPM-aligned listener/expressive extensions (pragmatic subset of LPM-Bench's
    //    78-emotion / 22-expression-base space, collapsed onto VRM presets) ──
    | 'amused'
    | 'curious'
    | 'embarrassed'
    | 'grateful'
    | 'tender'
    | 'proud'

export type PerformanceStateName = 'listen' | 'speak' | 'silence'

/**
 * Lightweight persona signal the director uses to bias *listening engagement*
 * and empathic lean. Kept dependency-free (no `@proj-aijade/agent-continuous-
 * learning` import) so `memory-pgvector` stays a leaf package; the upstream
 * `PersonaState` is a structural superset and can be passed in directly.
 */
export interface PerformancePersonaSignal {
  intimacy?: { warmth?: number, trust?: number, familiarity?: number, longing?: number }
  endocrine?: { cortisol?: number, adrenaline?: number, oxytocin?: number, serotonin?: number, dopamine?: number }
}

export interface PerformanceState {
  state: PerformanceStateName
  emotion: PerformanceEmotion
  gesture?: string
  gaze?: string
  music?: string
  /** Cumulative relationship delta with the user across the session (bounded). */
  relationDelta: number
  /** Live user-audio arousal (LPM "listen audio branch"), 0..1. Drives listening liveliness. */
  listenArousal: number
}

const EMOTION_WORDS: Array<[RegExp, PerformanceEmotion]> = [
  [/\b(ha+h+|lol|lmao|yay|great|awesome|love|excited|😄|😊|🥰)\b/i, 'happy'],
  [/\b(sad|sorry|miss|cry|😢|😭|💔)\b/i, 'sad'],
  [/\b(angry|mad|hate|ugh|annoy|😠|😡)\b/i, 'angry'],
  [/\b(wow|whoa|omg|really\?|surprise|😲|😮)\b/i, 'surprised'],
  [/\b(hmm|think|maybe|consider|perhaps|let me see)\b/i, 'thinking'],
  [/\b(love you|miss you|dear|sweetheart|💕|❤️)\b/i, 'loving'],
  [/\b(relax|calm|easy|breathe|peaceful)\b/i, 'calm'],
  [/\b(worried|anxious|nervous|scared|afraid|😟|😨)\b/i, 'worried'],
  [/\b(hehe|teehee|giggle|amusing|hilarious|rofl)\b/i, 'amused'],
  [/\b(curious|interesting|wonder|huh|what if)\b/i, 'curious'],
  [/\b(shy|oops|awkward|blush|embarrass)\b/i, 'embarrassed'],
  [/\b(thank|thanks|grateful|appreciate|tysm)\b/i, 'grateful'],
  [/\b(sweet|dear|precious|adorable|cute)\b/i, 'tender'],
  [/\b(proud|impressed|achievement|congrats|well done)\b/i, 'proud'],
]

const EMOTION_ALIASES: Record<string, PerformanceEmotion> = {
  joy: 'happy',
  joyous: 'happy',
  excited: 'happy',
  cheerful: 'happy',
  delighted: 'happy',
  fear: 'worried',
  afraid: 'worried',
  anxious: 'worried',
  mad: 'angry',
  furious: 'angry',
  ponder: 'thinking',
  contemplate: 'thinking',
  confused: 'thinking',
  peace: 'calm',
  peaceful: 'calm',
  amuse: 'amused',
  amusing: 'amused',
  funny: 'amused',
  intrigue: 'curious',
  intrigued: 'curious',
  bashful: 'embarrassed',
  thankful: 'grateful',
  cute: 'tender',
  adorable: 'tender',
  boast: 'proud',
}

/** One-step relaxation chain used for long-horizon anti-drift during `silence`. */
const RELAX_CHAIN: Record<PerformanceEmotion, PerformanceEmotion> = {
  neutral: 'neutral',
  angry: 'worried',
  worried: 'calm',
  calm: 'neutral',
  sad: 'calm',
  happy: 'calm',
  loving: 'calm',
  surprised: 'neutral',
  thinking: 'neutral',
  amused: 'happy',
  curious: 'surprised',
  embarrassed: 'happy',
  grateful: 'loving',
  tender: 'loving',
  proud: 'happy',
}

/** Bounds `relationDelta` so a long session cannot drift the character unboundedly (LPM stability). */
const RELATION_DELTA_BOUND = 10

function nowMs(): number {
  return typeof performance !== 'undefined' ? performance.now() : Date.now()
}

function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v
}

export interface PerformanceDirectorOptions {
  defaultEmotion?: PerformanceEmotion
  /** Called after every state/cue change so the UI can react in real time. */
  onState?: (state: PerformanceState) => void
}

function normalizeEmotion(value: string): PerformanceEmotion {
  const v = value.trim().toLowerCase()
  if (v in EMOTION_ALIASES)
    return EMOTION_ALIASES[v]
  if ((['neutral', 'happy', 'sad', 'angry', 'surprised', 'thinking', 'loving', 'calm', 'worried', 'amused', 'curious', 'embarrassed', 'grateful', 'tender', 'proud'] as const).includes(v as PerformanceEmotion))
    return v as PerformanceEmotion
  return 'neutral'
}

/**
 * Listening reaction scheduler — the LPM "listening is half of conversation"
 * engine. Produces brief non-verbal reactions (nod / glance / empathic lean)
 * whose *frequency* scales with the user-audio arousal (dual-stream listen
 * branch) and the persona engagement, and whose *selection* reflects the
 * relationship (high intimacy → more nodding / eye-contact; low → more reserved).
 */
const LISTEN_REACTIONS: ReadonlyArray<{ gesture?: string, gaze?: string }> = [
  { gesture: 'nod' }, // attentive agreement
  { gaze: 'user' }, // eye-contact / gaze-follow
  { gesture: 'nod', gaze: 'user' }, // combined acknowledgement
  { gaze: 'away' }, // thoughtful look-away
]

export class PerformanceDirector {
  private _state: PerformanceStateName = 'listen'
  private _emotion: PerformanceEmotion
  private _gesture: string | undefined
  private _gaze: string | undefined
  private _music: string | undefined
  private _relationDelta = 0
  private _emotionLocked = false
  private readonly _onState?: (state: PerformanceState) => void

  // ── LPM dual-stream "listen audio branch" ──
  private _listenArousal = 0
  private _listenEmotionHint: PerformanceEmotion | null = null

  // ── Listening reaction scheduler state ──
  private _listenReactionAt = 0
  private _reactionClearAt = 0
  private _personaEngagement = 0.5 // 0..1, default neutral

  constructor(opts: PerformanceDirectorOptions = {}) {
    this._emotion = opts.defaultEmotion ?? 'neutral'
    this._onState = opts.onState
  }

  /** Enter the listening state (called when a user turn starts). */
  enterListen(): void {
    this._state = 'listen'
    this._gesture = undefined
    this._gaze = undefined
    // First reaction after a short warm-up so it doesn't fire on the very first frame.
    this._listenReactionAt = nowMs() + 1500
    this._reactionClearAt = 0
    this._emit()
  }

  /**
   * Feed a streamed text chunk. On the first chunk the state flips to `speak`
   * immediately — this is the key to killing the silence gap. Emotion is guessed
   * from the lexicon unless an explicit marker has locked it.
   */
  onToken(literal: string): void {
    if (this._state === 'listen' || this._state === 'silence')
      this._state = 'speak'

    if (!this._emotionLocked)
      this._emotion = this._detectEmotion(literal, this._emotion)

    this._emit()
  }

  /** Apply a single parsed marker (from the `token-special` stream). */
  applyMarker(marker: PerformanceMarker): void {
    this._applyKey(marker.key, marker.value)
    this._emit()
  }

  /** Parse + apply every marker inside a chunk of text. */
  applyMarkers(text: string): void {
    for (const marker of parsePerformanceMarkers(text))
      this._applyKey(marker.key, marker.value)
    this._emit()
  }

  /** Turn ended: drop into the alive-idle `silence` state. */
  onTurnEnd(): void {
    this._state = 'silence'
    this._gesture = undefined
    this._gaze = undefined
    this._emit()
  }

  /**
   * LPM dual-stream audio cue. Call this from the ASR / audio pipeline with the
   * user's live speech level (0..1) and an optional emotion hint. The level is
   * exponentially smoothed into {@link _listenArousal}, which scales how lively
   * the listening reactions are; the emotion hint biases the *empathic lean*
   * (the avatar mirrors the user's valence softly while listening).
   *
   * Intentionally does **not** emit on every audio frame — arousal is sampled by
   * {@link tick} so we avoid per-frame chatter.
   */
  feedUserAudio(level: number, emotionHint?: PerformanceEmotion | null): void {
    this._listenArousal = 0.7 * this._listenArousal + 0.3 * clamp01(level)
    if (emotionHint)
      this._listenEmotionHint = emotionHint
  }

  /** Inject the live persona snapshot so listening engagement is relationship-aware (LPM). */
  setPersona(p?: PerformancePersonaSignal): void {
    const it = p?.intimacy
    const signals = [it?.warmth, it?.trust, it?.familiarity].filter((v): v is number => typeof v === 'number')
    const avg = signals.length ? signals.reduce((a, b) => a + b, 0) / signals.length : 0.5
    // Map [0,1] intimacy → [0.35, 1] engagement so strangers still react, friends react more.
    this._personaEngagement = 0.35 + 0.65 * clamp01(avg)
  }

  /**
   * Advance time-based behaviors. Call once per animation frame (or on a timer).
   * Drives: (1) listening reactions while `listen`; (2) emotion anti-drift
   * relaxation while `silence`. No-op in `speak` (the streamed tokens own that).
   */
  tick(now: number = nowMs()): void {
    if (this._state === 'listen') {
      // Clear an expired reaction (revert transient gesture/gaze/emotion lean).
      if ((this._gesture || this._gaze) && now >= this._reactionClearAt) {
        this._gesture = undefined
        this._gaze = undefined
        this._emit()
      }
      // Fire a fresh listening reaction once the schedule elapses.
      if (now >= this._listenReactionAt) {
        const reaction = LISTEN_REACTIONS[Math.floor(Math.random() * LISTEN_REACTIONS.length)]
        if (reaction.gesture)
          this._gesture = reaction.gesture
        if (reaction.gaze)
          this._gaze = reaction.gaze
        // Empathic lean: mirror the user's hint, else a soft relationship-based smile.
        if (!this._emotionLocked) {
          if (this._listenEmotionHint)
            this._emotion = this._listenEmotionHint
          else if (this._personaEngagement > 0.8)
            this._emotion = 'loving'
        }
        // High arousal + engagement → more frequent reactions (LPM liveliness).
        const liveliness = clamp01(this._listenArousal * 0.6 + this._personaEngagement * 0.4)
        const interval = 6000 - liveliness * 3600 // 6.0s → 2.4s
        this._listenReactionAt = now + interval
        this._reactionClearAt = now + 900
        this._emit()
      }
    }
    else if (this._state === 'silence') {
      // Long-horizon anti-drift: relax a non-neutral emotion one step toward the
      // baseline every few seconds so the avatar never freezes in a mood.
      if (!this._emotionLocked && this._emotion !== 'neutral' && now >= this._silenceRelaxAt) {
        this._emotion = RELAX_CHAIN[this._emotion]
        this._silenceRelaxAt = now + 4000
        this._emit()
      }
    }
  }

  /** Reset per-turn transient cues (keeps the cumulative `relationDelta`). */
  reset(): void {
    this._state = 'listen'
    this._emotion = 'neutral'
    this._gesture = undefined
    this._gaze = undefined
    this._music = undefined
    this._emotionLocked = false
    this._listenArousal = 0
    this._listenEmotionHint = null
    this._listenReactionAt = 0
    this._reactionClearAt = 0
    this._emit()
  }

  snapshot(): PerformanceState {
    return {
      state: this._state,
      emotion: this._emotion,
      gesture: this._gesture,
      gaze: this._gaze,
      music: this._music,
      relationDelta: this._relationDelta,
      listenArousal: this._listenArousal,
    }
  }

  get state(): PerformanceStateName {
    return this._state
  }

  get listenArousal(): number {
    return this._listenArousal
  }

  private _silenceRelaxAt = 0

  private _applyKey(key: PerformanceMarkerKey, value: string): void {
    const v = value.trim()
    switch (key) {
      case 'emotion':
        this._emotion = normalizeEmotion(v)
        this._emotionLocked = true
        break
      case 'gesture':
        this._gesture = v
        break
      case 'state':
        if (v === 'listen' || v === 'speak' || v === 'silence')
          this._state = v
        break
      case 'gaze':
        this._gaze = v
        break
      case 'music':
        this._music = v
        break
      case 'relation': {
        const n = Number.parseFloat(v)
        if (!Number.isNaN(n))
          this._relationDelta = Math.max(-RELATION_DELTA_BOUND, Math.min(RELATION_DELTA_BOUND, this._relationDelta + n))
        break
      }
    }
  }

  private _detectEmotion(text: string, fallback: PerformanceEmotion): PerformanceEmotion {
    for (const [re, emotion] of EMOTION_WORDS) {
      if (re.test(text))
        return emotion
    }
    return fallback
  }

  private _emit(): void {
    this._onState?.(this.snapshot())
  }
}

/** Factory symmetric with {@link import('../port').createLayeredMemoryPort}. */
export function createPerformanceDirector(opts?: PerformanceDirectorOptions): PerformanceDirector {
  return new PerformanceDirector(opts)
}
