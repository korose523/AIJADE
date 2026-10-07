/**
 * Tests for the determinism pre-check.
 *
 * Why these tests matter beyond coverage: `measureDeterminism` / `assertDeterminism`
 * are the *premise* of every reproducibility claim this project publishes — if the
 * check silently passed on a substrate that is actually diverging, every downstream
 * number would be unreproducible while looking verified. So we test the failure
 * path as carefully as the happy path.
 *
 * The second half of this file covers the **positive control**, which exists
 * because the failure mode above has a silent twin: a substrate that ignores the
 * sampling config entirely also produces identical outputs across seeds. The
 * tests that matter most there are the ones asserting we *refuse* to call that a
 * pass.
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

import {
  assertDeterminism,
  assertDeterminismAudit,
  auditDeterminism,
  hashText,
  measureDeterminism,
  runSamplingControl,
  SAMPLING_CONTROL_OVERRIDES,
} from './verify'

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

/**
 * A substrate whose behaviour depends on whether sampling was actually opened.
 *
 * This is the shape of the real defect: `samplingHonoured: false` models a
 * server that drops the sampling config, which looks exactly like greedy
 * decoding from the outside.
 */
function mkSamplingAwareSubstrate(opts: {
  samplingHonoured: boolean
  onSamplingRefused?: () => never
  emptyWhenSampling?: boolean
  checkOutput?: string
}): Substrate & { seeds: number[], samplings: SamplingConfig[] } {
  const seeds: number[] = []
  const samplings: SamplingConfig[] = []
  let samplingCalls = 0
  let checkCalls = 0
  return {
    seeds,
    samplings,
    async identity() {
      return { tag: 'test:latest', digest: 'deadbeef' }
    },
    async fingerprint() {
      return mkFingerprint()
    },
    async generate(options: GenerateOptions): Promise<GenerateResult> {
      const sampling = options.sampling ?? SAMPLING
      seeds.push(sampling.seed)
      samplings.push(sampling)

      // The control arm is the one with the sampler opened.
      const isSamplingArm = sampling.temperature > 0
      if (!isSamplingArm) {
        checkCalls += 1
        return {
          text: opts.checkOutput ?? 'greedy answer',
          fingerprint: mkFingerprint(sampling),
          model: 'test:latest',
          createdAt: new Date(0).toISOString(),
        }
      }

      if (opts.onSamplingRefused)
        opts.onSamplingRefused()

      samplingCalls += 1
      const text = opts.emptyWhenSampling
        ? ''
        : opts.samplingHonoured
          ? `sampled answer ${samplingCalls}`
          : 'frozen answer'
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

/* ------------------------------------------------------------------------- *
 * Positive control
 * ------------------------------------------------------------------------- */

describe('runSamplingControl', () => {
  it('reports "divergent" when opening the sampler changes the output', async () => {
    const sub = mkSamplingAwareSubstrate({ samplingHonoured: true })
    const report = await runSamplingControl(sub, MESSAGES, { runs: 3 })

    expect(report.verdict).toBe('divergent')
    expect(report.uniqueOutputs).toBe(3)
    expect(report.reason).toMatch(/demonstrably responds/)
  })

  it('reports "identical" when the substrate ignores the sampling config — the false-positive alarm', async () => {
    const sub = mkSamplingAwareSubstrate({ samplingHonoured: false })
    const report = await runSamplingControl(sub, MESSAGES, { runs: 3 })

    expect(report.verdict).toBe('identical')
    expect(report.uniqueOutputs).toBe(1)
    expect(report.reason).toMatch(/FALSE-POSITIVE ALARM/)
    expect(report.reason).toMatch(/Do NOT report the main check as a determinism pass/)
  })

  it('reports "indeterminate" when the server refuses the sampling request', async () => {
    const sub = mkSamplingAwareSubstrate({
      samplingHonoured: true,
      onSamplingRefused: () => {
        throw new Error('Ollama returned HTTP 400 Bad Request')
      },
    })
    const report = await runSamplingControl(sub, MESSAGES, { runs: 3 })

    expect(report.verdict).toBe('indeterminate')
    expect(report.error).toMatch(/HTTP 400/)
    expect(report.reason).toMatch(/UNKNOWN/)
    // Explicitly not a pass.
    expect(report.reason).toMatch(/not evidence that the main check passed/)
  })

  it('reports "indeterminate" when every completion is empty (the reasoning-model think trap)', async () => {
    const sub = mkSamplingAwareSubstrate({ samplingHonoured: true, emptyWhenSampling: true })
    const report = await runSamplingControl(sub, MESSAGES, { runs: 3 })

    // 3 identical empty strings hash the same — without the guard this would
    // masquerade as a clean "identical" false-positive-alarm result.
    expect(report.uniqueOutputs).toBe(1)
    expect(report.verdict).toBe('indeterminate')
    expect(report.reason).toMatch(/`think` trap/)
  })

  it('varies the seed on every control run — a fixed seed would "pass" while proving nothing', async () => {
    const sub = mkSamplingAwareSubstrate({ samplingHonoured: true })
    await runSamplingControl(sub, MESSAGES, { runs: 4 })

    expect(sub.seeds).toEqual([42, 42 + 7919, 42 + 2 * 7919, 42 + 3 * 7919])
  })

  it('widens temperature/top_k/top_p but leaves the rest of the config intact', async () => {
    const sub = mkSamplingAwareSubstrate({ samplingHonoured: true })
    const report = await runSamplingControl(sub, MESSAGES, { runs: 2 })

    expect(report.sampling).toEqual({
      ...SAMPLING,
      ...SAMPLING_CONTROL_OVERRIDES,
    })
    // Evidence fields an artifact can record.
    expect(report.samplingHash).toBeTruthy()
    expect(report.perRun.map(r => r.hash)).toHaveLength(2)
    expect(sub.samplings.every(s => s.temperature === SAMPLING_CONTROL_OVERRIDES.temperature)).toBe(true)
    expect(sub.samplings.every(s => s.num_ctx === SAMPLING.num_ctx)).toBe(true)
    expect(sub.samplings.every(s => s.think === false)).toBe(true)
  })

  it('accepts a caller-supplied override for the sampling arm', async () => {
    const sub = mkSamplingAwareSubstrate({ samplingHonoured: true })
    const report = await runSamplingControl(sub, MESSAGES, { runs: 2, sampling: { temperature: 1.3 } })

    expect(report.sampling.temperature).toBe(1.3)
  })

  it('never runs fewer than 2 repeats', async () => {
    const sub = mkSamplingAwareSubstrate({ samplingHonoured: true })
    const report = await runSamplingControl(sub, MESSAGES, { runs: 1 })

    expect(report.runs).toBe(2)
  })
})

describe('auditDeterminism', () => {
  it('passes only when the main check matches AND the control diverged', async () => {
    const sub = mkSamplingAwareSubstrate({ samplingHonoured: true })
    const audit = await auditDeterminism(sub, MESSAGES, { runs: 3, seedStrategy: 'varied' })

    expect(audit.verdict).toBe('pass')
    expect(audit.discriminative).toBe(true)
    expect(audit.falsePositiveRisk).toBe(false)
    expect(audit.check.identical).toBe(true)
    expect(audit.control.verdict).toBe('divergent')
    expect(audit.reason).toMatch(/not ignored sampling parameters/)
  })

  it('flags a FALSE POSITIVE when the main check matches but the control is frozen', async () => {
    // This is the mem0 case and the measured qwythos arm-B case: identical
    // outputs across seeds, but only because the sampler was never opened.
    const sub = mkSamplingAwareSubstrate({ samplingHonoured: false })
    const audit = await auditDeterminism(sub, MESSAGES, { runs: 3, seedStrategy: 'varied' })

    expect(audit.check.identical).toBe(true)
    expect(audit.control.verdict).toBe('identical')
    expect(audit.verdict).toBe('false-positive-risk')
    expect(audit.discriminative).toBe(false)
    expect(audit.falsePositiveRisk).toBe(true)
    expect(audit.reason).toMatch(/FALSE-POSITIVE ALARM/)
  })

  it('is inconclusive — never a pass — when the control cannot run', async () => {
    const sub = mkSamplingAwareSubstrate({
      samplingHonoured: true,
      onSamplingRefused: () => {
        throw new Error('model does not support sampling')
      },
    })
    const audit = await auditDeterminism(sub, MESSAGES, { runs: 3 })

    expect(audit.verdict).toBe('inconclusive-control')
    expect(audit.discriminative).toBe(false)
    // The main check matched, so that match is unverified and must be flagged.
    expect(audit.falsePositiveRisk).toBe(true)
    expect(audit.reason).toMatch(/UNDECIDED/)
  })

  it('reports non-deterministic when the main check diverges on a substrate that does respond to sampling', async () => {
    let call = 0
    const sub: Substrate = {
      async identity() {
        return { tag: 'test:latest', digest: 'deadbeef' }
      },
      async fingerprint() {
        return mkFingerprint()
      },
      async generate(options: GenerateOptions): Promise<GenerateResult> {
        const sampling = options.sampling ?? SAMPLING
        const text = sampling.temperature > 0 ? `sampled ${sampling.seed}` : `greedy ${call++}`
        return {
          text,
          fingerprint: mkFingerprint(sampling),
          model: 'test:latest',
          createdAt: new Date(0).toISOString(),
        }
      },
    }

    const audit = await auditDeterminism(sub, MESSAGES, { runs: 3, seedStrategy: 'varied' })

    expect(audit.verdict).toBe('non-deterministic')
    expect(audit.discriminative).toBe(true)
    expect(audit.falsePositiveRisk).toBe(false)
    expect(audit.check.uniqueOutputs).toBe(3)
    expect(audit.reason).toMatch(/Genuinely non-deterministic/)
  })

  it('still calls it non-deterministic when the control is blind but the main check diverged', async () => {
    // Divergence is a real observation no matter what the control says; the
    // audit must not launder it into "false positive".
    let call = 0
    const sub: Substrate = {
      async identity() {
        return { tag: 'test:latest', digest: 'deadbeef' }
      },
      async fingerprint() {
        return mkFingerprint()
      },
      async generate(options: GenerateOptions): Promise<GenerateResult> {
        const sampling = options.sampling ?? SAMPLING
        const text = sampling.temperature > 0 ? 'frozen' : `greedy ${call++}`
        return {
          text,
          fingerprint: mkFingerprint(sampling),
          model: 'test:latest',
          createdAt: new Date(0).toISOString(),
        }
      },
    }

    const audit = await auditDeterminism(sub, MESSAGES, { runs: 3, seedStrategy: 'varied' })

    expect(audit.verdict).toBe('non-deterministic')
    expect(audit.discriminative).toBe(false)
    expect(audit.reason).toMatch(/regardless/)
  })

  it('leaves measureDeterminism untouched: the check sub-report has no verdict field', async () => {
    const sub = mkSamplingAwareSubstrate({ samplingHonoured: false })
    const audit = await auditDeterminism(sub, MESSAGES, { runs: 3 })

    // The nested check must be the *original* shape so existing consumers of
    // DeterminismReport keep working unchanged.
    expect(Object.keys(audit.check).sort()).toEqual(
      ['fingerprint', 'identical', 'perRun', 'runs', 'seedStrategy', 'uniqueOutputs'].sort(),
    )
    expect(audit.check.identical).toBe(true)
  })
})

describe('assertDeterminismAudit', () => {
  it('returns the audit when the verdict is pass', async () => {
    const sub = mkSamplingAwareSubstrate({ samplingHonoured: true })
    const audit = await assertDeterminismAudit(sub, MESSAGES, { runs: 3 })

    expect(audit.verdict).toBe('pass')
  })

  it('throws on a false positive instead of letting it pass', async () => {
    const sub = mkSamplingAwareSubstrate({ samplingHonoured: false })

    await expect(assertDeterminismAudit(sub, MESSAGES, { runs: 3 })).rejects.toThrow(/false-positive-risk/)
  })

  it('throws on an unrunnable control — "unknown" is not "pass"', async () => {
    const sub = mkSamplingAwareSubstrate({
      samplingHonoured: true,
      onSamplingRefused: () => {
        throw new Error('HTTP 500')
      },
    })

    await expect(assertDeterminismAudit(sub, MESSAGES, { runs: 3 })).rejects.toThrow(/inconclusive-control/)
  })

  it('puts the control config and hashes in the error so the failure is diagnosable', async () => {
    const sub = mkSamplingAwareSubstrate({ samplingHonoured: false })

    await expect(assertDeterminismAudit(sub, MESSAGES, { runs: 3 })).rejects.toThrow(/control hashes/)
  })

  it('throws on genuine non-determinism', async () => {
    const sub = mkSubstrate(['a', 'b', 'c'])
    const audit = await auditDeterminism(sub, MESSAGES, { runs: 3 }).catch(() => undefined)

    // mkSubstrate ignores sampling entirely, so the control is blind AND the
    // main check diverges: a true negative.
    expect(audit?.verdict).toBe('non-deterministic')
    await expect(assertDeterminismAudit(sub, MESSAGES, { runs: 3 })).rejects.toThrow(/non-deterministic/)
  })
})
