/**
 * Direct OpenAI-compatible client for a local FunASR / SenseVoice server
 * (see services/speech/sensevoice_asr_server.py).
 *
 * Why this exists: `@xsai`'s streaming transcription only surfaces `textStream`,
 * so the user's detected emotion (`<|HAPPY|>`, `<|ANGRY|>`, …) is dropped on the
 * floor. For the bidirectional "over-persona" voice loop we POST a (short)
 * utterance to `POST /v1/audio/transcriptions` with `response_format=verbose_json`
 * and read back `{ text, language, emotion, event }`.
 */

export interface FunASRTranscriptionResult {
  text: string
  language?: string | null
  emotion?: string | null
  event?: string | null
  model?: string | null
}

export async function transcribeFunASR(params: {
  baseUrl: string
  model?: string
  file: Blob | File
  language?: string
}): Promise<FunASRTranscriptionResult> {
  const url = `${params.baseUrl.replace(/\/+$/, '')}/audio/transcriptions`
  const form = new FormData()
  form.append('model', params.model ?? 'SenseVoiceSmall')
  form.append('file', params.file)
  form.append('response_format', 'verbose_json')
  if (params.language)
    form.append('language', params.language)

  const res = await fetch(url, { method: 'POST', body: form })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`FunASR transcription failed (${res.status}): ${detail.slice(0, 200)}`)
  }
  return await res.json() as FunASRTranscriptionResult
}

/**
 * Map a SenseVoice emotion label (e.g. "HAPPY", "happy", "<|NEUTRAL|>") to an
 * AIJADE Emotion name. AIJADE's Emotion enum is
 * Happy/Sad/Angry/Think/Surprise/Awkward/Question/Curious/Neutral — it has no
 * Fearful/Disgusted, so those fall back to neutral.
 */
const SENSEVOICE_TO_AIJADE: Record<string, string> = {
  HAPPY: 'happy',
  SAD: 'sad',
  ANGRY: 'angry',
  SURPRISED: 'surprised',
  NEUTRAL: 'neutral',
  FEARFUL: 'neutral',
  DISGUSTED: 'neutral',
}

export function senseVoiceEmotionToAijade(label?: string | null): string | null {
  if (!label)
    return null
  const key = label.toUpperCase().replace(/[<>|]/g, '').trim()
  if (!key)
    return null
  return SENSEVOICE_TO_AIJADE[key] ?? 'neutral'
}

/**
 * Wrap a list of 16-bit PCM mono audio chunks into a standard WAV Blob that
 * FunASR / torchaudio can decode. Used to feed the live mic stream (Int16 @
 * 16 kHz) back to the ASR engine for per-sentence emotion detection.
 */
export function pcm16ChunksToWavBlob(chunks: ArrayBuffer[], sampleRate = 16000): Blob {
  let total = 0
  for (const c of chunks)
    total += c.byteLength

  const wav = new ArrayBuffer(44 + total)
  const view = new DataView(wav)

  const writeString = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i++)
      view.setUint8(offset + i, s.charCodeAt(i))
  }

  writeString(0, 'RIFF')
  view.setUint32(4, 36 + total, true)
  writeString(8, 'WAVE')
  writeString(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // mono
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true) // byte rate
  view.setUint16(32, 2, true) // block align
  view.setUint16(34, 16, true) // bits per sample
  writeString(36, 'data')
  view.setUint32(40, total, true)

  let offset = 44
  for (const c of chunks) {
    new Uint8Array(wav, offset, c.byteLength).set(new Uint8Array(c))
    offset += c.byteLength
  }

  return new Blob([wav], { type: 'audio/wav' })
}
