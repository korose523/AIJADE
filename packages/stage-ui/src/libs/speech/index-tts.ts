/**
 * Direct OpenAI-compatible client for IndexTTS2's local `tts_server.py`.
 *
 * Why this exists: `@xsai/generate-speech` only forwards the OpenAI-standard
 * fields (model / input / voice / speed / response_format). IndexTTS2 extends
 * the endpoint with emotion + voice-cloning fields (`emo_text`, `emo_vector`,
 * `voice_audio`) that xsai would otherwise drop. So for the over-persona voice
 * loop we POST multipart/form-data ourselves.
 *
 * Endpoint (see D:/项目/index-tts/tts_server.py):
 *   POST {baseUrl}/audio/speech   (baseUrl e.g. http://localhost:8765/v1)
 */

export interface IndexTTSSynthesizeParams {
  baseUrl: string
  model?: string
  input: string
  voice?: string
  /** Free-text emotion, e.g. "happy and excited" (IndexTTS2 emo_text). */
  emoText?: string
  /** 8-dim emotion vector (IndexTTS2 emo_vector). */
  emoVector?: number[]
  /** Reference audio for zero-shot timbre cloning (IndexTTS2 voice_audio). */
  voiceAudio?: Blob
  responseFormat?: string
}

export async function synthesizeIndexTTS(
  params: IndexTTSSynthesizeParams,
): Promise<ArrayBuffer> {
  const url = `${params.baseUrl.replace(/\/+$/, '')}/audio/speech`
  const form = new FormData()
  form.append('model', params.model ?? 'indextts2')
  form.append('input', params.input)
  form.append('voice', params.voice ?? 'default')
  form.append('response_format', params.responseFormat ?? 'wav')
  if (params.emoText)
    form.append('emo_text', params.emoText)
  if (params.emoVector)
    form.append('emo_vector', JSON.stringify(params.emoVector))
  if (params.voiceAudio)
    form.append('voice_audio', params.voiceAudio)

  const res = await fetch(url, { method: 'POST', body: form })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(
      `IndexTTS synthesis failed (${res.status}): ${detail.slice(0, 200)}`,
    )
  }
  return await res.arrayBuffer()
}

/** Map AIJADE persona emotion names to IndexTTS2 emo_text phrases. */
const INDEX_TTS_EMO_TEXT: Record<string, string> = {
  happy: 'happy and cheerful',
  sad: 'sad and gentle',
  angry: 'angry and intense',
  surprised: 'surprised',
  fearful: 'fearful',
  disgusted: 'disgusted',
  neutral: 'calm and neutral',
}

export function emoTextFor(emotionName?: string | null): string | undefined {
  if (!emotionName)
    return undefined
  return INDEX_TTS_EMO_TEXT[emotionName] ?? emotionName
}
