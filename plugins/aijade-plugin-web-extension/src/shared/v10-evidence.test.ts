import { describe, expect, it } from 'vitest'

import { reducePageToEvidence, reduceSubtitleToEvidence } from './v10-evidence'

describe('v10 evidence reduction', () => {
  it('reduces page context without creating causal refs', () => {
    const event = reducePageToEvidence({
      site: 'youtube',
      url: 'https://example.test/article',
      title: 'A title',
      description: 'A summary',
    })
    expect(event?.topic).toBe('aijade.video.observation.webpage_text')
    expect(event?.payload).toMatchObject({
      source_url: 'https://example.test/article',
      observation_text: 'A title. A summary',
    })
    expect(event?.payload).not.toHaveProperty('intent_ref')
    expect(event?.payload).not.toHaveProperty('render_ref')
  })

  it('reduces subtitles to bounded time spans', () => {
    const event = reduceSubtitleToEvidence({
      site: 'youtube',
      url: 'https://youtube.test/watch?v=abc',
      videoId: 'abc',
      text: '  hello   world ',
      startMs: 1000,
      endMs: 2200,
    })
    expect(event?.payload).toMatchObject({
      video_id: 'abc',
      caption_text: 'hello world',
      time_spans: [{ start_ms: 1000, end_ms: 2200, text: 'hello world' }],
    })
  })

  it('rejects evidence without a stable source', () => {
    expect(reducePageToEvidence({
      site: 'unknown',
      url: '',
      title: 'title',
    })).toBeNull()
    expect(reduceSubtitleToEvidence({
      site: 'unknown',
      url: 'https://example.test',
      text: 'caption',
    })).toBeNull()
  })
})
