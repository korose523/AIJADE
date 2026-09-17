import type { PageContextPayload, SubtitlePayload } from './types'

export interface V10EvidenceEvent {
  topic: 'aijade.video.observation.webpage_text' | 'aijade.video.observation.video_transcript'
  payload: Record<string, unknown>
  inputText: string
}

function normalize(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}

function stableHash(value: string): string {
  let hash = 2166136261
  for (let index = 0; index < value.length; index++) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return `fnv1a:${(hash >>> 0).toString(16).padStart(8, '0')}`
}

export function reducePageToEvidence(page: PageContextPayload): V10EvidenceEvent | null {
  const text = normalize([page.title, page.description].filter(Boolean).join('. '))
  if (!text || !page.url)
    return null

  return {
    topic: 'aijade.video.observation.webpage_text',
    inputText: text,
    payload: {
      source_url: page.url,
      content_hash: stableHash(text),
      spans: [{ start_offset: 0, end_offset: text.length, label: 'page-summary' }],
      observation_text: text,
    },
  }
}

export function reduceSubtitleToEvidence(subtitle: SubtitlePayload): V10EvidenceEvent | null {
  const text = normalize(subtitle.text)
  if (!text || !subtitle.videoId)
    return null

  const startMs = Math.max(0, subtitle.startMs ?? 0)
  const endMs = Math.max(startMs, subtitle.endMs ?? startMs)
  return {
    topic: 'aijade.video.observation.video_transcript',
    inputText: text,
    payload: {
      video_id: subtitle.videoId,
      transcript_hash: stableHash(text),
      time_spans: [{ start_ms: startMs, end_ms: endMs, text }],
      caption_text: text,
    },
  }
}
