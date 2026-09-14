/**
 * Direct client for a LOCAL CosyVoice server (FunAudioLLM/CosyVoice
 * `cosyvoice/cli/model.py` or `examples/llm/api_server.py`) — specifically its
 * "Instruct" emotion mode, which OpenAI-compatible clients (and `@xsai`) cannot
 * forward. This mirrors libs/speech/index-tts.ts: a native endpoint call that
 * bypasses the standard speech path so the *voice* (not just the avatar face)
 * carries the persona's feeling.
 *
 * Local server endpoint: POST {baseUrl}/inference_instruct
 *   body: { model, tts_text, spk_id, instruct_text, stream }
 *   returns: raw audio bytes (wav)
 */

export interface CosyVoiceSynthParams {
  baseUrl: string
  model?: string
  input: string
  /** CosyVoice speaker id, e.g. "中文女". Maps to `spk_id`. */
  voice?: string
  /** Instruct phrase, e.g. "Speak in a happy, cheerful tone." */
  instruct?: string
  stream?: boolean
}

export async function synthesizeCosyVoice(params: CosyVoiceSynthParams): Promise<ArrayBuffer> {
  const url = `${params.baseUrl.replace(/\/+$/, '')}/inference_instruct`
  const body = {
    model: params.model ?? 'cosyvoice-v1',
    tts_text: params.input,
    spk_id: params.voice ?? '中文女',
    instruct_text: params.instruct ?? '',
    stream: params.stream ?? false,
  }

  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`CosyVoice synth failed (${res.status}): ${detail.slice(0, 200)}`)
  }
  return await res.arrayBuffer()
}

/**
 * Map an AIJADE Emotion name to a CosyVoice Instruct phrase.
 * AIJADE Emotion enum: Happy/Sad/Angry/Think/Surprise/Awkward/Question/Curious/Neutral
 */
const AIJADE_TO_INSTRUCT: Record<string, string> = {
  happy: 'Speak in a happy, cheerful tone.',
  sad: 'Speak in a sad, gentle tone.',
  angry: 'Speak in an angry, intense tone.',
  surprised: 'Speak in a surprised tone.',
  think: 'Speak in a thoughtful, calm tone.',
  awkward: 'Speak in an awkward, hesitant tone.',
  question: 'Speak in a questioning tone.',
  curious: 'Speak in a curious, interested tone.',
  neutral: 'Speak in a neutral, calm tone.',
}

export function instructTextFor(emotionName?: string | null): string | undefined {
  if (!emotionName)
    return undefined
  return AIJADE_TO_INSTRUCT[emotionName] ?? AIJADE_TO_INSTRUCT.neutral
}
