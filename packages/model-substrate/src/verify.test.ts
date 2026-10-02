/**
 * Tests for the determinism pre-check.
 *
 * Why these tests matter beyond coverage: `measureDeterminism` / `assertDeterminism`
 * are the *premise* of every reproducibility claim this project publishes — if the
 * check silently passed on a substrate that is actually diverging, every downstream
 * number would be unreproducible while looking verified. So we test the failure
 * path as carefully as the happy path.
 *
 * Note the tests use an injected fake substrate: the point is the *decision logic*
 * (count distinct outputs, compare seeds, throw vs. return), not any real model.
 */

import type {
  ChatMessage,
  GenerateOptions,
  GenerateResult,
  RunFingerprint,
  SamplingConfig,
  Substrate,
} from './types'

import { describe, expect, it } from 'vitest'

import { assertDeterminism, hashText, measureDeterminism } from './verify'

const SAMPLING: SamplingConfig = {
  temperature: 0,
  seed: 42,
  top_p: 1,
  top_k: 1,
  repeat_penalty: 1,
  num_ctx: 4096,
  num_predict: 256,
  think: false,
}

const MESSAGES: ChatMessage[] = [{ role: 'user', content: 'ping' }]

function mkFingerprint(sampling: SamplingConfig = SAMPLING): RunFingerprint {
  return {
    schema: 'aijade.run_fingerprint@1',
    mode: 'research',
    model: { tag: 'test:latest', digest: 'deadbeef' },
    sampling,
    samplingHash: 'sampling-hash',
    fingerprint: 'run-fingerprint',
  }
}

/**
 * A substrate that emits `texts` in order (cycling) and records the seed it was
 * called with, so tests can assert on the seed strategy too.
 */
function mkSubstrate(texts: string[]): Substrate & { seeds: number[] } {
  let call = 0
  const seeds: number[] = []
  return {
    seeds,
    async identity() {
      return { tag: 'test:latest', digest: 'deadbeef' }
    },
    async fingerprint() {
      return mkFingerprint()
    },
    async generate(options: GenerateOptions): Promise<GenerateResult> {
      const sampling = options.sampling ?? SAMPLING
      seeds.push(sampling.seed)
      const text = texts[call % texts.length]
      call += 1
      return {
        text,
        fingerprint: mkFingerprint(sampling),
        model: 'test:latest',
        createdAt: new Date(0).toISOString(),
      }
    },
  }
}

describe('measureDeterminism', () => {
  it('reports identical when every repeat produces the same text', async () => {
    const sub = mkSubstrate(['same', 'same', 'same', 'same', 'same'])
    const report = await measureDeterminism(sub, MESSAGES, { runs: 5, seedStrategy: 'varied' })

    expect(report.identical).toBe(true)
    expect(report.uniqueOutputs).toBe(1)
    expect(report.runs).toBe(5)
    expect(report.perRun).toHaveLength(5)
    expect(report.seedStrategy).toBe('varied')
  })

  it('detects divergence and reports how many distinct outputs there were', async () => {
    // 'a', 'b', 'a', 'c', 'b' -> three distinct texts
    const sub = mkSubstrate(['a', 'b', 'a', 'c', 'b'])
    const report = await measureDeterminism(sub, MESSAGES, { runs: 5, seedStrategy: 'varied' })

    expect(report.identical).toBe(false)
    expect(report.uniqueOutputs).toBe(3)
  })

  it('under seedStrategy "varied" each run gets a different seed', async () => {
    const sub = mkSubstrate(['x', 'x', 'x'])
    await measureDeterminism(sub, MESSAGES, { runs: 3, seedStrategy: 'varied' })

    expect(sub.seeds).toEqual([42, 42 + 7919, 42 + 2 * 7919])
  })

  it('under seedStrategy "fixed" every run reuses the base seed', async () => {
    const sub = mkSubstrate(['x', 'x', 'x'])
    await measureDeterminism(sub, MESSAGES, { runs: 3, seedStrategy: 'fixed' })

    expect(sub.seeds).toEqual([42, 42, 42])
  })

  it('never runs fewer than 2 repeats', async () => {
    const sub = mkSubstrate(['x', 'x'])
    const report = await measureDeterminism(sub, MESSAGES, { runs: 1 })

    expect(report.runs).toBe(2)
  })

  it('defaults to 5 runs and the fixed-seed strategy', async () => {
    const sub = mkSubstrate(['x', 'x', 'x', 'x', 'x'])
    const report = await measureDeterminism(sub, MESSAGES)

    expect(report.runs).toBe(5)
    expect(report.seedStrategy).toBe('fixed')
  })
})

describe('assertDeterminism', () => {
  it('returns the report when the substrate reproduces itself', async () => {
    const sub = mkSubstrate(['ok', 'ok', 'ok'])
    const report = await assertDeterminism(sub, MESSAGES, { runs: 3 })

    expect(report.identical).toBe(true)
  })

  it('throws instead of proceeding on a non-reproducible substrate', async () => {
    const sub = mkSubstrate(['a', 'b'])

    await expect(assertDeterminism(sub, MESSAGES, { runs: 2 })).rejects.toThrow(/Non-deterministic decoding/)
  })

  it('names the distinct output count in the error so the failure is diagnosable', async () => {
    const sub = mkSubstrate(['a', 'b', 'c'])

    await expect(assertDeterminism(sub, MESSAGES, { runs: 3 })).rejects.toThrow(/3 distinct outputs/)
  })
})

describe('hashText', () => {
  it('is stable for equal input', () => {
    expect(hashText('abc')).toBe(hashText('abc'))
  })

  it('distinguishes different input', () => {
    expect(hashText('abc')).not.toBe(hashText('abd'))
  })
})
