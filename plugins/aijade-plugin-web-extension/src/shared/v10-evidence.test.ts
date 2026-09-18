import type { LlmCall, LlmOutput } from './llm'

import { describe, expect, it, vi } from 'vitest'

import { evaluatePageOpinion, reducePageToEvidence, reduceSubtitleToEvidence, stableHash, summarizePageToEvidence, summarizeSubtitleToEvidence } from './v10-evidence'

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

  it('does not add session_id when none is provided (caller always supplies one in production)', () => {
    const event = reducePageToEvidence({
      site: 'youtube',
      url: 'https://example.test/article',
      title: 'A title',
      description: 'A summary',
    })
    expect(event?.payload).not.toHaveProperty('session_id')
  })
})

describe('v10 evidence P2-3 real body text', () => {
  it('prefers bodyText + spans over title/description when present', () => {
    const body = 'First paragraph about the topic. Second paragraph with more detail.'
    const event = reducePageToEvidence({
      site: 'youtube',
      url: 'https://example.test/article',
      title: 'A title',
      description: 'A summary',
      bodyText: body,
      spans: [
        { start_offset: 0, end_offset: 39, label: 'p' },
        { start_offset: 40, end_offset: 78, label: 'p' },
      ],
    })
    expect(event?.payload.observation_text).toBe(body)
    expect(event?.payload.spans).toEqual([
      { start_offset: 0, end_offset: 39, label: 'p' },
      { start_offset: 40, end_offset: 78, label: 'p' },
    ])
    // content_hash 必须对实际写入的 observation_text 重算（防漂移）。
    expect(event?.payload.content_hash).toBe(stableHash(body))
    // 正文存在时不得混入 title/description 的回退口径。
    expect(event?.payload.observation_text).not.toContain('A title')
  })

  it('falls back to title+description when bodyText is empty (unchanged behaviour)', () => {
    const event = reducePageToEvidence({
      site: 'youtube',
      url: 'https://example.test/article',
      title: 'A title',
      description: 'A summary',
      bodyText: '   ',
    })
    expect(event?.payload.observation_text).toBe('A title. A summary')
    expect(event?.payload.spans).toEqual([{ start_offset: 0, end_offset: 18, label: 'page-summary' }])
  })
})

describe('v10 evidence session_id injection', () => {
  const SESSION = 'install-id-abc-123'

  it('reducePageToEvidence embeds the provided session_id', () => {
    const event = reducePageToEvidence({
      site: 'youtube',
      url: 'https://example.test/article',
      title: 'A title',
      description: 'A summary',
    }, { sessionId: SESSION })
    expect(event?.payload.session_id).toBe(SESSION)
  })

  it('reduceSubtitleToEvidence embeds the provided session_id', () => {
    const event = reduceSubtitleToEvidence({
      site: 'youtube',
      url: 'https://youtube.test/watch?v=abc',
      videoId: 'abc',
      text: '  hello   world ',
    }, { sessionId: SESSION })
    expect(event?.payload.session_id).toBe(SESSION)
  })

  it('summarizePageToEvidence embeds the provided session_id', async () => {
    const llm: LlmCall = async () => ({ summary: 'The page is about AI.', key_points: [], confidence: 0.9 })
    const event = await summarizePageToEvidence({
      site: 'youtube',
      url: 'https://example.test/article',
      title: 'A title',
      description: 'A summary',
    }, llm, { sessionId: SESSION })
    expect(event?.payload.session_id).toBe(SESSION)
  })

  it('summarizeSubtitleToEvidence embeds the provided session_id', async () => {
    const llm: LlmCall = async () => ({ summary: 'Caption summary.', key_points: [], confidence: 0.7 })
    const event = await summarizeSubtitleToEvidence({
      site: 'youtube',
      url: 'https://youtube.test/watch?v=abc',
      videoId: 'abc',
      text: '  hello   world ',
    }, llm, { sessionId: SESSION })
    expect(event?.payload.session_id).toBe(SESSION)
  })

  it('evaluatePageOpinion payload never carries session_id (different topic, no such field)', async () => {
    const llm: LlmCall = async () => ({
      claims: [{ claim_text: 'A claim', confidence: 0.8 }],
      uncertainty_notes: 'Confidence limited by missing sources.',
    })
    const result = await evaluatePageOpinion({
      site: 'youtube',
      url: 'https://example.test/article',
      title: 'A title',
      description: 'A summary',
    }, llm)
    expect(result?.topic).toBe('aijade.learning.constraint.opinion_evaluation')
    expect(result?.payload).not.toHaveProperty('session_id')
  })
})

describe('v10 evidence LLM paths', () => {
  const page = {
    site: 'youtube' as const,
    url: 'https://example.test/article',
    title: 'A title',
    description: 'A summary',
  }

  const subtitle = {
    site: 'youtube' as const,
    url: 'https://youtube.test/watch?v=abc',
    videoId: 'abc',
    text: '  hello   world ',
    startMs: 1000,
    endMs: 2200,
  }

  it('summarizePageToEvidence produces an event with a drift-proof content_hash', async () => {
    const llm: LlmCall = async (): Promise<LlmOutput> => ({
      summary: 'The page is about AI.',
      key_points: ['Point one', 'Point two'],
      confidence: 0.9,
    })
    const event = await summarizePageToEvidence(page, llm)
    expect(event?.topic).toBe('aijade.video.observation.webpage_text')
    const observationText = event?.payload.observation_text as string
    // 防漂移断言：content_hash 必须是对**实际写入**的 observation_text 的重算值。
    expect(event?.payload.content_hash).toBe(stableHash(observationText))
    expect(observationText).toBe('The page is about AI. Point one Point two')
  })

  it('summarizeSubtitleToEvidence hashes the summarized caption_text', async () => {
    const llm: LlmCall = async (): Promise<LlmOutput> => ({
      summary: 'Caption summary.',
      key_points: [],
      confidence: 0.7,
    })
    const event = await summarizeSubtitleToEvidence(subtitle, llm)
    const captionText = event?.payload.caption_text as string
    expect(event?.payload.transcript_hash).toBe(stableHash(captionText))
  })

  it('summarizePageToEvidence returns null when LLM yields no usable summary', async () => {
    const llm: LlmCall = async (): Promise<LlmOutput> => ({ summary: '', confidence: 0.1 })
    expect(await summarizePageToEvidence(page, llm)).toBeNull()
  })

  it('summarizePageToEvidence returns null when LLM throws (caller falls back)', async () => {
    const llm: LlmCall = async () => { throw new Error('boom') }
    const spy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(await summarizePageToEvidence(page, llm)).toBeNull()
    spy.mockRestore()
  })

  it('evaluatePageOpinion returns null when claims are empty', async () => {
    const llm: LlmCall = async (): Promise<LlmOutput> => ({
      claims: [],
      uncertainty_notes: 'Not enough info.',
    })
    expect(await evaluatePageOpinion(page, llm)).toBeNull()
  })

  it('evaluatePageOpinion returns null when uncertainty_notes is empty', async () => {
    const llm: LlmCall = async (): Promise<LlmOutput> => ({
      claims: [{ claim_text: 'A claim', confidence: 0.8 }],
      uncertainty_notes: '',
    })
    expect(await evaluatePageOpinion(page, llm)).toBeNull()
  })

  it('evaluatePageOpinion returns a valid payload on success', async () => {
    const llm: LlmCall = async (): Promise<LlmOutput> => ({
      claims: [{ claim_text: 'A claim', confidence: 0.8 }],
      uncertainty_notes: 'Confidence limited by missing sources.',
    })
    const result = await evaluatePageOpinion(page, llm)
    expect(result?.topic).toBe('aijade.learning.constraint.opinion_evaluation')
    expect(result?.payload.claims).toHaveLength(1)
    expect(result?.payload.uncertainty_notes).toBe('Confidence limited by missing sources.')
    expect(typeof result?.payload.evaluation_target).toBe('string')
    expect(result?.payload.evaluation_target.length).toBeGreaterThan(0)
  })

  it('evaluatePageOpinion returns null when LLM output is unparseable', async () => {
    const llm: LlmCall = async (): Promise<LlmOutput | undefined> => undefined
    expect(await evaluatePageOpinion(page, llm)).toBeNull()
  })
})
