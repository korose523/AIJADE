import { describe, expect, it } from 'vitest'

import {
  assertCompleteSampling,
  assertResearchMode,
  buildFingerprint,
  fnv1a,
  hashSampling,
  RESEARCH_SAMPLING,
} from './index'
import { SamplingError } from './types'

describe('fnv1a', () => {
  it('is stable and returns 8 hex chars', () => {
    expect(fnv1a('aijade')).toBe(fnv1a('aijade'))
    expect(fnv1a('aijade')).toMatch(/^[0-9a-f]{8}$/)
  })

  it('separates similar inputs', () => {
    expect(fnv1a('temperature=0')).not.toBe(fnv1a('temperature=1'))
  })
})

describe('hashSampling', () => {
  it('is independent of property insertion order', () => {
    const a = { temperature: 0, seed: 42, top_p: 1, top_k: 1, repeat_penalty: 1, num_ctx: 512, num_predict: 8, think: true }
    const b = { think: true, num_predict: 8, num_ctx: 512, repeat_penalty: 1, top_k: 1, top_p: 1, seed: 42, temperature: 0 }
    expect(hashSampling(a)).toBe(hashSampling(b))
  })

  it('changes when any single parameter changes', () => {
    const base = { ...RESEARCH_SAMPLING }
    for (const key of ['temperature', 'seed', 'top_p', 'top_k', 'repeat_penalty', 'num_ctx', 'num_predict'] as const) {
      const mutated = { ...base, [key]: (base[key] as number) + 1 }
      expect(hashSampling(mutated)).not.toBe(hashSampling(base))
    }
  })
})

describe('assertCompleteSampling', () => {
  it('accepts a fully specified config', () => {
    expect(() => assertCompleteSampling({ ...RESEARCH_SAMPLING })).not.toThrow()
  })

  it('rejects a config missing a key instead of falling back to server defaults', () => {
    const partial = { ...RESEARCH_SAMPLING } as Record<string, unknown>
    delete partial.seed
    expect(() => assertCompleteSampling(partial as never)).toThrow(SamplingError)
  })

  it('rejects NaN', () => {
    expect(() => assertCompleteSampling({ ...RESEARCH_SAMPLING, temperature: Number.NaN })).toThrow(SamplingError)
  })
})

describe('assertResearchMode', () => {
  it('accepts greedy decoding', () => {
    expect(() => assertResearchMode({ ...RESEARCH_SAMPLING })).not.toThrow()
  })

  it('rejects any non-zero temperature', () => {
    expect(() => assertResearchMode({ ...RESEARCH_SAMPLING, temperature: 0.6 })).toThrow(/temperature=0/)
  })
})

describe('buildFingerprint', () => {
  const model = { tag: 'qwythos', digest: 'sha256:abc123' }

  it('carries the schema, mode, sampling and identity', () => {
    const fp = buildFingerprint('research', model, { ...RESEARCH_SAMPLING }, '0.33.3')
    expect(fp.schema).toBe('aijade.substrate/1')
    expect(fp.mode).toBe('research')
    expect(fp.samplingHash).toBe(hashSampling(RESEARCH_SAMPLING))
    expect(fp.serverVersion).toBe('0.33.3')
    expect(fp.fingerprint).toMatch(/^[0-9a-f]{8}$/)
  })

  it('produces different ids for different weights', () => {
    const a = buildFingerprint('research', { tag: 'qwythos', digest: 'sha256:aaa' }, { ...RESEARCH_SAMPLING })
    const b = buildFingerprint('research', { tag: 'qwythos', digest: 'sha256:bbb' }, { ...RESEARCH_SAMPLING })
    expect(a.fingerprint).not.toBe(b.fingerprint)
  })

  it('produces different ids for different server versions', () => {
    const a = buildFingerprint('research', model, { ...RESEARCH_SAMPLING }, '0.33.3')
    const b = buildFingerprint('research', model, { ...RESEARCH_SAMPLING }, '0.34.0')
    expect(a.fingerprint).not.toBe(b.fingerprint)
  })

  it('differs between research and interactive mode at identical sampling', () => {
    const a = buildFingerprint('research', model, { ...RESEARCH_SAMPLING })
    const b = buildFingerprint('interactive', model, { ...RESEARCH_SAMPLING })
    expect(a.fingerprint).not.toBe(b.fingerprint)
  })
})
