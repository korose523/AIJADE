import { describe, expect, it } from 'vitest'

import { parseChatCompletion, parseJsonContent } from './index'

describe('parseChatCompletion', () => {
  it('extracts text, model and usage from an OpenAI payload', () => {
    const raw = {
      id: 'chatcmpl-1',
      model: 'qwen2.5:7b',
      choices: [{ index: 0, message: { role: 'assistant', content: 'hello' }, finish_reason: 'stop' }],
      usage: { prompt_tokens: 10, completion_tokens: 3, total_tokens: 13 },
    }
    const c = parseChatCompletion(raw, 'fallback')
    expect(c.text).toBe('hello')
    expect(c.model).toBe('qwen2.5:7b')
    expect(c.finishReason).toBe('stop')
    expect(c.usage?.totalTokens).toBe(13)
  })

  it('tolerates missing usage / choices', () => {
    const c = parseChatCompletion({}, 'fallback')
    expect(c.text).toBe('')
    expect(c.model).toBe('fallback')
    expect(c.usage).toBeNull()
  })
})

describe('parseJsonContent', () => {
  it('parses a bare JSON object', () => {
    expect(parseJsonContent('{"a":1}')).toEqual({ a: 1 })
  })

  it('strips a ```json fence', () => {
    const out = parseJsonContent('```json\n{"a":[1,2]}\n```')
    expect(out).toEqual({ a: [1, 2] })
  })

  it('extracts JSON embedded in prose', () => {
    const out = parseJsonContent('Sure! Here is the result: {"ok":true} hope that helps')
    expect(out).toEqual({ ok: true })
  })

  it('throws on non-JSON input', () => {
    expect(() => parseJsonContent('not json at all')).toThrow()
  })
})
