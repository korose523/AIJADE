import type { LlmOutput } from './llm'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { chatCompletion, extractJsonObject, summarize } from './llm'

/** 构造一个符合 OpenAI Chat Completions 形状的 fetch mock。 */
function mockFetch(response: { status?: number, body: unknown }) {
  const status = response.status ?? 200
  const fetchMock = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => response.body,
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  return fetchMock
}

beforeEach(() => {
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('chatCompletion', () => {
  it('succeeds on 200 with OpenAI-shaped content', async () => {
    mockFetch({ body: { choices: [{ message: { content: 'hello' } }] } })
    const res = await chatCompletion('http://localhost:6121', { messages: [{ role: 'user', content: 'x' }] })
    expect(res.ok).toBe(true)
    if (res.ok)
      expect(res.content).toBe('hello')
  })

  it('maps 401 to unauthorized', async () => {
    mockFetch({ status: 401, body: { error: 'unauthorized' } })
    const res = await chatCompletion('http://localhost:6121', { messages: [] })
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.kind).toBe('unauthorized')
  })

  it('401 without token → unauthorized + reason "missing" (user must configure a credential)', async () => {
    mockFetch({ status: 401, body: { error: 'unauthorized' } })
    const res = await chatCompletion('http://localhost:6121', { messages: [] })
    expect(res.ok).toBe(false)
    if (!res.ok) {
      expect(res.kind).toBe('unauthorized')
      expect(res.reason).toBe('missing')
    }
  })

  it('401 with token → unauthorized + reason "rejected" (credential present but invalid/expired)', async () => {
    mockFetch({ status: 401, body: { error: 'unauthorized' } })
    const res = await chatCompletion('http://localhost:6121', { messages: [], token: 'stale' })
    expect(res.ok).toBe(false)
    if (!res.ok) {
      expect(res.kind).toBe('unauthorized')
      expect(res.reason).toBe('rejected')
    }
  })

  it('maps 402 to payment_required (expected failure, not a bug)', async () => {
    mockFetch({ status: 402, body: { error: 'insufficient balance' } })
    const res = await chatCompletion('http://localhost:6121', { messages: [] })
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.kind).toBe('payment_required')
  })

  it('maps 503 to unavailable (config-guard missing key)', async () => {
    mockFetch({ status: 503, body: { error: 'FLUX_PER_REQUEST missing' } })
    const res = await chatCompletion('http://localhost:6121', { messages: [] })
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.kind).toBe('unavailable')
  })

  it('maps network rejection to network', async () => {
    globalThis.fetch = (() => Promise.reject(new Error('dns failed'))) as unknown as typeof fetch
    const res = await chatCompletion('http://localhost:6121', { messages: [] })
    expect(res.ok).toBe(false)
    if (!res.ok) {
      expect(res.kind).toBe('network')
      expect(res.status).toBe(0)
    }
  })

  it('treats 200 with missing content as malformed', async () => {
    mockFetch({ status: 200, body: { choices: [] } })
    const res = await chatCompletion('http://localhost:6121', { messages: [] })
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.kind).toBe('malformed')
  })
})

describe('extractJsonObject', () => {
  it('parses bare JSON', () => {
    expect(extractJsonObject('{"a":1}')).toEqual({ a: 1 })
  })

  it('parses fenced json', () => {
    const text = 'Here you go:\n```json\n{"summary":"x","key_points":["a"],"confidence":0.5}\n```'
    expect(extractJsonObject(text)).toMatchObject({ summary: 'x' })
  })

  it('parses JSON surrounded by prose', () => {
    const text = 'Sure! {"claims":[{"claim_text":"t","confidence":0.9}],"uncertainty_notes":"n"} done.'
    expect(extractJsonObject(text)).toMatchObject({ uncertainty_notes: 'n' })
  })

  it('returns undefined for non-JSON text', () => {
    expect(extractJsonObject('no json here at all')).toBeUndefined()
    expect(extractJsonObject('')).toBeUndefined()
  })
})

describe('summarize', () => {
  it('returns parsed object on normal JSON content', async () => {
    const out: LlmOutput = { summary: 'S', key_points: ['a', 'b'], confidence: 0.8 }
    mockFetch({ body: { choices: [{ message: { content: JSON.stringify(out) } }] } })
    const result = await summarize('some text', { kind: 'page' })
    expect(result).toMatchObject({ summary: 'S', key_points: ['a', 'b'], confidence: 0.8 })
  })

  it('still parses content wrapped in ```json fences', async () => {
    const out: LlmOutput = { summary: 'S', key_points: ['a'], confidence: 0.5 }
    mockFetch({ body: { choices: [{ message: { content: `\`\`\`json\n${JSON.stringify(out)}\n\`\`\`` } }] } })
    const result = await summarize('some text', { kind: 'page' })
    expect(result?.summary).toBe('S')
  })

  it('returns undefined when model emits non-JSON text', async () => {
    mockFetch({ body: { choices: [{ message: { content: 'I cannot summarize that.' } }] } })
    const result = await summarize('some text', { kind: 'page' })
    expect(result).toBeUndefined()
  })

  it('returns undefined on 401 (expected auth failure)', async () => {
    mockFetch({ status: 401, body: { error: 'unauthorized' } })
    const result = await summarize('some text', { kind: 'page' })
    expect(result).toBeUndefined()
  })
})
