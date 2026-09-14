import { describe, expect, it } from 'vitest'

import {
  createOllamaSubstrate,
  QWYTHOS_INTERACTIVE_SAMPLING,
  RESEARCH_SAMPLING,
} from './client'
import { SamplingError } from './types'

describe('createOllamaSubstrate', () => {
  it('requires a model', () => {
    expect(() => createOllamaSubstrate({ model: '' })).toThrow(SamplingError)
  })

  it('defaults to interactive mode with the Qwythos sampling preset', () => {
    const s = createOllamaSubstrate({ model: 'qwythos' })
    expect(s.options.mode).toBe('interactive')
    expect(s.options.baseUrl).toBe('http://localhost:11434')
  })

  it('enforces greedy decoding in research mode', () => {
    const s = createOllamaSubstrate({ model: 'qwythos', mode: 'research' })
    expect(s.options.mode).toBe('research')
    // The default research config must actually be deterministic.
    expect(RESEARCH_SAMPLING.temperature).toBe(0)
  })

  it('refuses research mode with a non-zero temperature', () => {
    expect(() =>
      createOllamaSubstrate({
        model: 'qwythos',
        mode: 'research',
        sampling: { ...RESEARCH_SAMPLING, temperature: 0.6 },
      }),
    ).toThrow(/temperature=0/)
  })

  it('refuses an incomplete sampling config rather than defaulting silently', () => {
    const partial = { ...QWYTHOS_INTERACTIVE_SAMPLING } as Record<string, unknown>
    delete partial.top_k
    expect(() =>
      createOllamaSubstrate({ model: 'qwythos', sampling: partial as never }),
    ).toThrow(SamplingError)
  })

  it('does not mutate the preset objects it is handed', () => {
    const before = { ...RESEARCH_SAMPLING }
    createOllamaSubstrate({ model: 'qwythos', mode: 'research', sampling: RESEARCH_SAMPLING })
    expect(RESEARCH_SAMPLING).toEqual(before)
  })

  it('normalises a trailing slash on baseUrl', () => {
    const s = createOllamaSubstrate({ model: 'qwythos', baseUrl: 'http://localhost:11434/' })
    expect(s.options.baseUrl).toBe('http://localhost:11434')
  })
})
