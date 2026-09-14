/**
 * Structured "performance" markers for AIJADE, inspired by **LPM 1.0**
 * (Large Performance Model, arXiv:2604.07823): conversation is modelled as a
 * performance* — not just language, but rhythm, gaze, hesitation and micro
 * expressions. LPM drives a character through three real-time states
 * (`[Listen]` / `[Speak]` / `[Silence]`) and multimodal controls
 * (text → action/emotion, audio → speak/listen, image → identity).
 *
 * We expose the same idea as a tiny, LLM-authorable marker vocabulary the
 * model can emit inline (`<|emotion:happy|>`), mirroring AIJADE's existing
 * `<|...|>` special-marker stream. The orchestrator already strips these from
 * the speech channel and routes them through `token-special` hooks, so the
 * avatar / TTS can react without waiting for the full reply.
 */
export type PerformanceMarkerKey
  = | 'emotion'
    | 'gesture'
    | 'state'
    | 'gaze'
    | 'music'
    | 'relation'

export interface PerformanceMarker {
  key: PerformanceMarkerKey
  value: string
}

const MARKER_KEYS = 'emotion|gesture|state|gaze|music|relation'
const MARKER_RE = new RegExp(`<\\|(${MARKER_KEYS}):([^|]+)\\|>`, 'g')

/** Parse all `<|key:value|>` performance markers from a chunk of model text. */
export function parsePerformanceMarkers(text: string): PerformanceMarker[] {
  const out: PerformanceMarker[] = []
  for (const match of text.matchAll(MARKER_RE)) {
    out.push({ key: match[1] as PerformanceMarkerKey, value: match[2].trim() })
  }
  return out
}

/** Serialise a partial performance state into authorable markers. */
export function authorPerformanceMarkers(
  state: Partial<Record<PerformanceMarkerKey, string>>,
): string {
  return Object.entries(state)
    .filter(([, v]) => v != null && v !== '')
    .map(([k, v]) => `<|${k}:${v}|>`)
    .join(' ')
}

/**
 * System-prompt guidance teaching the model to emit performance markers.
 * Drop this into the system supplement so the structured-performance channel
 * is opt-in and self-describing (LPM-style: tell the model how to "act").
 */
export const PERFORMANCE_MARKER_PROMPT = [
  'You can enrich replies with inline performance markers (stripped from the',
  'spoken voice, consumed by the avatar). Use them sparingly and only when',
  'they add life:',
  '- <|emotion:happy|> one of: neutral, happy, sad, angry, surprised, thinking, loving, calm, worried',
  '- <|gesture:wave|> a short body/face action hint (e.g. wave, nod, tilt, think)',
  '- <|state:speak|> force a performance state: listen | speak | silence',
  '- <|gaze:user|> where attention points: user | away | object',
  '- <|music:calm|> an optional ambient music mood',
  '- <|relation:+1|> relationship delta with the user, e.g. +1 / -1',
].join(' ')
