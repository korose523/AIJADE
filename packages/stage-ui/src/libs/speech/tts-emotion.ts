/**
 * Generic over-persona TTS emotion registry.
 *
 * Some local TTS engines (IndexTTS2, CosyVoice) accept emotion parameters that
 * OpenAI-compatible clients / `@xsai` cannot forward. For those we register a
 * direct synth* that talks to the engine's native (emotion-capable) endpoint.
 *
 * Stage.vue looks up the active provider here. When a capability exists it uses
 * the direct synth (emotion optional) instead of the generic `@xsai` path, so
 * the *voice* itself expresses the persona's feeling — not just the avatar
 * face. Engines without an entry fall through to the standard speech path.
 */

import { instructTextFor, synthesizeCosyVoice } from './cosyvoice'
import { emoTextFor, synthesizeIndexTTS } from './index-tts'

export interface TtsEmotionSynthOptions {
  baseUrl?: string
  model?: string
  input: string
  voice?: string
  /** AIJADE emotion name (Happy/Sad/Angry/Think/.../Neutral) or null. */
  emotionName?: string | null
}

export interface TtsEmotionCapability {
  /** When true, this provider MUST always use directSynth (non-OpenAI endpoint). */
  alwaysDirect?: boolean
  /** Bypass `@xsai`; talk to the engine's native emotion-capable endpoint. */
  directSynth: (opts: TtsEmotionSynthOptions) => Promise<ArrayBuffer | null>
}

const registry: Record<string, TtsEmotionCapability> = {
  'index-tts-vllm': {
    // IndexTTS2 can also fall back to the standard OpenAI-compatible path when
    // no emotion is active, so it is NOT always-direct.
    alwaysDirect: false,
    directSynth: async ({ baseUrl, model, input, voice, emotionName }) => {
      if (!emotionName)
        return null
      return await synthesizeIndexTTS({
        baseUrl: baseUrl || 'http://localhost:8765/v1',
        model,
        input,
        voice,
        emoText: emoTextFor(emotionName),
      })
    },
  },
  'cosyvoice-local': {
    // CosyVoice Instruct mode is only exposed by the local (non-OpenAI) server,
    // so this provider must ALWAYS use the direct synth.
    alwaysDirect: true,
    directSynth: async ({ baseUrl, model, input, voice, emotionName }) => {
      return await synthesizeCosyVoice({
        baseUrl: baseUrl || 'http://localhost:9000',
        model,
        input,
        voice,
        instruct: instructTextFor(emotionName),
      })
    },
  },
}

export function getTtsEmotionCapability(providerId: string): TtsEmotionCapability | null {
  return registry[providerId] ?? null
}
