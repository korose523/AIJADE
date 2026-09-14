/**
 * useAvatarAnimation — bridges AIJADE's structured performance layer
 * (`@proj-aijade/memory-pgvector/performance`) onto a VRM avatar.
 *
 * It drives two things:
 *  - Body/clip state via AnimationStateMachine (talk / listen / idle). When the
 *    corresponding AnimationClips are not loaded (the common case — today only
 *    the idle clip ships), those transitions are safe no-ops, so the avatar
 *    simply keeps idling and the structured state is still tracked.
 *  - Facial expression via the VRM expression manager (through `useVRMEmote`):
 *    the PerformanceDirector's emotion + gesture cues are mapped to VRM emote
 *    presets (happy / sad / angry / surprised / think / neutral). This is the
 *    part that visibly reacts in real time.
 *
 * Design mirrors LPM 1.0's three real-time states (listen / speak / silence)
 * and the multimodal performance markers (arXiv:2604.07823).
 */

import type { VRM } from '@pixiv/three-vrm'
import type { PerformanceEmotion, PerformanceState } from '@proj-aijade/memory-pgvector/performance'
import type { AnimationAction, AnimationClip, AnimationMixer } from 'three'

import type { PAD, PersonaSignal } from '../../libs/emotion/avatar-expression'
import type { MotionEntry, MotionFusionLibrary } from '../../libs/motion-fusion'

import { LoopOnce, LoopRepeat } from 'three'

import {
  emotionIntensity,
  IdleSpontaneousController,
  normalizeEmotionLabel,
  padToPreset,

  personaToIdleBias,
} from '../../libs/emotion/avatar-expression'
import { personaToMotionIntent } from '../../libs/motion-fusion'
import { AnimationStateMachine } from './animation-state-machine'

/** PerformanceEmotion → VRM emote preset (keys match useVRMEmote's emotionStates). */
const EMOTION_TO_VRM: Record<PerformanceEmotion, string> = {
  neutral: 'neutral',
  happy: 'happy',
  sad: 'sad',
  angry: 'angry',
  surprised: 'surprised',
  thinking: 'think',
  loving: 'happy',
  calm: 'neutral',
  worried: 'sad',
  // ── LPM-aligned listener/expressive extensions (collapsed onto the 6 VRM presets) ──
  amused: 'happy',
  curious: 'surprised',
  embarrassed: 'happy',
  grateful: 'happy',
  tender: 'happy',
  proud: 'happy',
}

/** One-shot gesture → a brief VRM emote pulse (best-effort; no clip assets needed). */
const GESTURE_TO_VRM_EMOTE: Record<string, string> = {
  wave: 'happy',
  dance: 'happy',
  cheer: 'happy',
  celebrate: 'happy',
  agree: 'happy',
  nod: 'happy',
  disagree: 'angry',
  shrug: 'sad',
  point: 'surprised',
}

/** Gestures that should loop while active (otherwise they play once and clamp). */
const GESTURE_LOOP: Record<string, boolean> = {
  dance: true,
  celebrate: true,
  cheer: true,
}

/**
 * Spontaneous micro-animation when the user goes quiet (leuke's silence clock +
 * refractory cooldown). Keeps the avatar feeling alive during pauses instead of
 * freezing on a single idle pose.
 */
const idleCtrl = new IdleSpontaneousController({
  pool: ['think', 'nod', 'shrug'],
  idleThresholdMs: 4500,
  cooldownMs: 9000,
})

export interface AvatarEmote {
  setEmotion: (name: string, intensity?: number) => void
  setEmotionWithResetAfter?: (name: string, ms: number, intensity?: number) => void
}

export function useAvatarAnimation(
  _vrm: VRM | null,
  mixer: AnimationMixer | null,
  clips: AnimationClip[] = [],
  emote?: AvatarEmote,
  gestureClips: AnimationClip[] = [],
  /** Performance-cue blink modulation (LPM-style: fewer blinks while speaking). */
  blink?: { setEngaged: (engaged: boolean) => void, setRateScale?: (scale: number) => void },
  /** Performance-cue gaze: called with the live `gaze` marker (LPM-style look target). */
  onGaze?: (dir: string | null) => void,
  /** Live persona snapshot — drives persona-aware autonomous idle behavior. */
  persona?: PersonaSignal,
  /** Merged KIMODO + HY-Motion persona-fusable motion library. */
  motionLibrary?: MotionFusionLibrary,
) {
  const sm = new AnimationStateMachine()

  const clipMap = new Map<string, AnimationClip>()
  for (const clip of clips)
    clipMap.set(clip.name, clip)

  // Prefer the fused library's clips (so persona source-selection works);
  // fall back to the raw gestureClips param for backward compatibility.
  let currentLibrary = motionLibrary
  const sourceClips = currentLibrary ? currentLibrary.entries.map(e => e.clip) : gestureClips
  const gestureClipMap = new Map<string, AnimationClip>()
  for (const clip of sourceClips)
    gestureClipMap.set(clip.name, clip)

  let currentAction: AnimationAction | null = null
  let currentClipName: string | null = null
  let gestureAction: AnimationAction | null = null

  /** Play a real offline gesture clip (crossfaded with the current body action). */
  function playGestureClip(name: string): boolean {
    if (!mixer)
      return false
    const clip = gestureClipMap.get(name)
    if (!clip)
      return false
    const action = mixer.clipAction(clip)
    const loop = GESTURE_LOOP[name] ?? false
    action.reset()
    action.setLoop(loop ? LoopRepeat : LoopOnce, loop ? Infinity : 1)
    action.clampWhenFinished = !loop
    action.enabled = true
    action.setEffectiveWeight(1)
    action.play()
    if (currentAction && currentAction !== action)
      currentAction.crossFadeTo(action, 0.3, false)
    else
      action.fadeIn(0.3)
    gestureAction = action
    return true
  }

  function stopGestureClip(): void {
    if (!mixer || !gestureAction)
      return
    const prev = gestureAction
    if (currentAction && currentAction !== prev)
      prev.crossFadeTo(currentAction, 0.3, false)
    else
      prev.fadeOut(0.3)
    gestureAction = null
  }

  /** Play a specific fused motion entry (crossfaded; loop-aware). */
  function playMotionEntry(entry: MotionEntry): boolean {
    if (!mixer)
      return false
    const action = mixer.clipAction(entry.clip)
    const loop = GESTURE_LOOP[entry.name] ?? false
    action.reset()
    action.setLoop(loop ? LoopRepeat : LoopOnce, loop ? Infinity : 1)
    action.clampWhenFinished = !loop
    action.enabled = true
    action.setEffectiveWeight(1)
    action.play()
    if (currentAction && currentAction !== action)
      currentAction.crossFadeTo(action, 0.3, false)
    else
      action.fadeIn(0.3)
    gestureAction = action
    return true
  }

  sm.onTransition = ({ clip, crossfade }) => {
    if (!mixer)
      return
    const targetClip = clipMap.get(clip)
    if (!targetClip)
      return // clip not loaded → safe no-op (avatar keeps idling)
    const next = mixer.clipAction(targetClip)
    next.reset().play()
    if (currentAction && currentAction !== next)
      currentAction.crossFadeTo(next, crossfade, false)
    else
      next.fadeIn(crossfade)
    currentAction = next
    currentClipName = clip
  }

  sm.onGesture = ({ gesture, active }) => {
    if (!active || !gesture) {
      stopGestureClip()
      return
    }
    // Prefer a real offline body clip; fall back to an emote pulse if none exists.
    const played = playGestureClip(gesture)
    if (!played) {
      const expr = GESTURE_TO_VRM_EMOTE[gesture]
      if (expr && emote?.setEmotionWithResetAfter)
        emote.setEmotionWithResetAfter(expr, 2500)
    }
  }

  let lastEmotion: PerformanceEmotion | null = null
  let lastGesture: string | undefined
  let lastGaze: string | undefined
  let lastEngaged: boolean | null = null
  let currentPersona = persona

  function applyEmotion(emotion: PerformanceEmotion): void {
    if (emotion === lastEmotion)
      return
    lastEmotion = emotion
    // Normalize to a known VRM preset (arbitrary LLM labels -> valid preset).
    const preset = normalizeEmotionLabel(EMOTION_TO_VRM[emotion] ?? 'neutral')
    emote?.setEmotion(preset, emotionIntensity(emotion))
  }

  /**
   * Translate a structured performance snapshot into avatar actions.
   *
   * While the avatar is *speaking* it holds a single coherent expression and
   * re-arms the silence clock. While the user is *not* speaking (listen OR
   * silence — LPM's two "listener" phases) the avatar is "on its own" and its
   * autonomous behavior fires: a persona-fused KIMODO×HY-Motion body clip, plus
   * a subtle face drift + gaze + blink cadence, all derived from `PersonaSignal`.
   * This is the "super-personified" core — the body literally expresses the
   * avatar's internal relationship + hormonal state, not a fixed random pool.
   */
  function applyPerformance(state: PerformanceState): void {
    const userSpeaking = state.state === 'speak'

    if (userSpeaking) {
      sm.fire('speak')
      applyEmotion(state.emotion)
      idleCtrl.reset() // avatar talking → re-arm the listener/silence clock
    }
    else {
      // ── user is NOT speaking: listen or silence ──
      sm.fire(state.state === 'listen' ? 'listen' : 'speak-end')
      // LPM: the listener's visible reaction reflects emotion + relationship, not
      // a frozen neutral face. The director feeds an attentive baseline / empathic
      // lean (and, when wired, the dual-stream user-audio hint) through `state.emotion`.
      applyEmotion(state.state === 'listen' ? (state.emotion ?? 'neutral') : 'neutral')

      const now = performance.now()
      if (currentPersona) {
        const bias = personaToIdleBias(currentPersona)
        const intentWeights = personaToMotionIntent(currentPersona)
        idleCtrl.setPool(bias.pool)
        idleCtrl.tick(now, true, (g) => {
          // Body: persona-fused clip. Prefer an exact gesture-name match (source
          // chosen by persona), else let the intent weights pick the best fit.
          const entry = currentLibrary?.pickForName(g, intentWeights.sourcePreference)
            ?? currentLibrary?.select(intentWeights)
            ?? null
          if (entry)
            playMotionEntry(entry)
          else if (g)
            sm.playGesture(g) // no clip → fall back to an emote pulse
          // Face: subtle persona emotion drift (fires only at trigger → no jitter).
          if (bias.emotion)
            emote?.setEmotionWithResetAfter?.(normalizeEmotionLabel(EMOTION_TO_VRM[bias.emotion] ?? 'neutral'), 2500, 0.3)
          // Gaze: persona gaze bias (fires only at trigger → no jitter).
          if (bias.gazeBias)
            onGaze?.(bias.gazeBias)
        })
        blink?.setRateScale?.(bias.blinkRateScale)
      }
      else {
        idleCtrl.tick(now, true, (g) => {
          if (g)
            sm.playGesture(g)
        })
      }
    }

    if (state.gesture !== lastGesture) {
      if (state.gesture)
        sm.playGesture(state.gesture)
      else
        sm.endGesture()
      lastGesture = state.gesture
    }

    // Blink / gaze now react to performance cues (LPM 1.0 listen/speak/silence),
    // not just random timers. While speaking the avatar holds eye contact
    // (blink cadence stretched); on listen/silence it returns to natural rhythm.
    const engaged = userSpeaking
    if (engaged !== lastEngaged) {
      lastEngaged = engaged
      blink?.setEngaged(engaged)
    }
    // A `gaze` marker (e.g. <|gaze: left|>) nudges the look-at target; the Vue
    // layer maps it to vrm.lookAt via `onGaze`.
    if (state.gaze !== lastGaze) {
      lastGaze = state.gaze
      onGaze?.(state.gaze ?? null)
    }
  }

  return {
    sm,
    applyPerformance,
    /**
     * Drive the face from a continuous PAD vector (astrbot_plugin_emotion_spirit
     * style). Collapses onto the dominant VRM preset + intensity so the emotion
     * engine can weight it smoothly.
     */
    setEmotionPAD: (pad: PAD) => {
      const { preset, intensity } = padToPreset(pad)
      emote?.setEmotion(preset, intensity)
    },
    // ── Manual controls (kept for non-performance-driven callers) ──
    speak: () => sm.fire('speak'),
    listen: () => sm.fire('listen'),
    idle: () => sm.fire('speak-end'),
    gesture: (name: string) => sm.playGesture(name),
    endGesture: () => sm.endGesture(),
    get current() {
      return sm.getCurrent()
    },
    get currentClip() {
      return currentClipName
    },
    /** Update the live persona snapshot without rebuilding the whole driver. */
    setPersona: (p?: PersonaSignal) => { currentPersona = p },
    /** Swap / refresh the fused motion library (e.g. after async clip load). */
    setMotionLibrary: (lib?: MotionFusionLibrary) => {
      currentLibrary = lib
      if (lib) {
        gestureClipMap.clear()
        for (const clip of lib.entries.map(e => e.clip))
          gestureClipMap.set(clip.name, clip)
      }
    },
  }
}
