/**
 * SpeechFacade — unified speech abstraction (Architecture Reorg Phase 1).
 *
 * Converges three previously-scattered "over-persona" concerns into ONE
 * contract so there is a single source of truth instead of three hand-wired
 * call sites:
 *
 *   1. TTS emotion routing  — was `getTtsEmotionCapability` in tts-emotion.ts,
 *      consumed by Stage.vue's speech pipeline.
 *   2. Listened (user) emotion state — was `currentUserEmotionName` +
 *      `setUserEmotion`/`clearUserEmotion` in hearing.ts, written by the ASR
 *      emotion probe and read by chat.ts for system-prompt injection.
 *   3. System-prompt emotion injection — was inline in chat.ts
 *      `getSystemPromptSupplement`.
 *
 * The facade is intentionally a *thin* wrapper (REORG_PLAN: "facade 包一层").
 * It owns the shared state + the unified entry points, but the actual audio
 * decode and the generic @xsai TTS fallback stay in Stage.vue (they need the
 * live AudioContext), and BroadcastChannel (Layer C) is NOT touched here.
 *
 * Downstream phases (2–5) build on this contract.
 */

import type { FunASRTranscriptionResult } from './funasr'
import type { TtsEmotionCapability, TtsEmotionSynthOptions } from './tts-emotion'

import { ref } from 'vue'

import {

  senseVoiceEmotionToAijade,
  transcribeFunASR,
} from './funasr'
import {
  getTtsEmotionCapability as _getTtsEmotionCapability,

} from './tts-emotion'

/* ------------------------------------------------------------------ *
 * 1. TTS emotion capability (Layer B: provider registry → direct synth)*
 * ------------------------------------------------------------------ */

export type { TtsEmotionCapability, TtsEmotionSynthOptions }

/**
 * Single lookup for "does this TTS provider support an emotion-capable
 * direct synth (IndexTTS2 / local CosyVoice native endpoints)?"
 * Re-exported from tts-emotion.ts so callers converge on the facade.
 */
export function getTtsEmotionCapability(providerId: string): TtsEmotionCapability | null {
  return _getTtsEmotionCapability(providerId)
}

/**
 * Perform the emotion-capable direct synth for a provider. Returns null when
 * the provider has no registered capability. The caller (Stage.vue) still
 * owns audio decode + the generic @xsai fallback, since those need the live
 * AudioContext — the facade only routes the direct-synth call.
 */
export async function synthesizeEmotionDirect(
  providerId: string,
  opts: TtsEmotionSynthOptions,
): Promise<ArrayBuffer | null> {
  const cap = getTtsEmotionCapability(providerId)
  if (!cap)
    return null
  return await cap.directSynth(opts)
}

/* ------------------------------------------------------------------ *
 * 2. Listened (user) emotion state — single source of truth          *
 * ------------------------------------------------------------------ */

/**
 * The user's currently-detected emotion (from the local ASR engine), fed
 * back into the LLM conversation context so the persona can react to how the
 * user is feeling (bidirectional over-persona loop). This ref is THE one
 * shared instance — hearing.ts probes it, chat.ts reads it.
 */
export const currentUserEmotionName = ref<string | null>(null)

export function setUserEmotion(name: string | null) {
  currentUserEmotionName.value = name
}

export function clearUserEmotion() {
  currentUserEmotionName.value = null
}

/**
 * Map a raw SenseVoice / FunASR emotion label and push it into the shared
 * listened-emotion state. Normalises via senseVoiceEmotionToAijade; no-op when
 * the label maps to null.
 */
export function reportListenedEmotion(rawLabel?: string | null): void {
  const emotion = senseVoiceEmotionToAijade(rawLabel)
  if (emotion)
    setUserEmotion(emotion)
}

/* ------------------------------------------------------------------ *
 * 3. Unified ASR transcription + emotion probe                       *
 * ------------------------------------------------------------------ */

export interface TranscribeOptions {
  baseUrl: string
  file: Blob | File
  model?: string
  language?: string
}

export interface TranscribeResult {
  text: string
  language?: string | null
  /** AIJADE emotion name (already normalised), or null. */
  emotion?: string | null
}

/**
 * Transcribe audio via the local FunASR / SenseVoice server and automatically
 * feed the detected user emotion into the listened-emotion state (over-persona
 * bidirectional loop). Returns both the text and the normalised emotion.
 */
export async function transcribe(opts: TranscribeOptions): Promise<TranscribeResult> {
  const probe: FunASRTranscriptionResult = await transcribeFunASR(opts)
  const emotion = senseVoiceEmotionToAijade(probe.emotion)
  if (emotion)
    setUserEmotion(emotion)
  return { text: probe.text, language: probe.language, emotion }
}

/* ------------------------------------------------------------------ *
 * 4. System-prompt emotion injection (consumed by chat.ts)           *
 * ------------------------------------------------------------------ */

/**
 * Append the listened user-emotion note to a base system prompt. Returns the
 * base unchanged when no emotion is currently detected. Used by chat.ts
 * `getSystemPromptSupplement` so the injection logic lives in exactly one
 * place.
 */
export function systemPromptEmotionSupplement(base: string): string {
  const userEmotion = currentUserEmotionName.value
  if (!userEmotion)
    return base
  return `${base}\n\n[User emotional state] The user is currently speaking with a ${userEmotion} tone. Reflect this in your reply's tone and wording where natural.`
}
