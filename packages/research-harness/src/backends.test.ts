import { BENCH_TASKS, runTask } from '@proj-aijade/skill-bench-env'
import { describe, expect, it } from 'vitest'

import { buildGeneratePrompt, createMockBackend } from './backends'

const sample = BENCH_TASKS.slice(0, 5)

describe('mock backend determinism', () => {
  it('produces an identical candidate sequence for the same seed', async () => {
    const b1 = createMockBackend(12345, { pCorrect: 0.5 })
    const b2 = createMockBackend(12345, { pCorrect: 0.5 })
    for (const task of sample) {
      for (let attempt = 0; attempt < 4; attempt++) {
        const g1 = await b1.generate(task, { attempt })
        const g2 = await b2.generate(task, { attempt })
        expect(g1).toBe(g2)
      }
    }
  })

  it('verify is deterministic for the same seed and same candidate', async () => {
    // A separate backend produces a candidate; the two verify backends start from
    // the same seed with no prior RNG consumption, so they must agree.
    const gen = createMockBackend(777, { pCorrect: 0.5, hallucination: 0.3, miss: 0.1 })
    const cand = await gen.generate(sample[0], { attempt: 0 })
    const b1 = createMockBackend(777, { pCorrect: 0.5, hallucination: 0.3, miss: 0.1 })
    const b2 = createMockBackend(777, { pCorrect: 0.5, hallucination: 0.3, miss: 0.1 })
    const v1 = await b1.verify(sample[0], cand)
    const v2 = await b2.verify(sample[0], cand)
    expect(v1.verdict).toBe(v2.verdict)
    expect(v1.score).toBe(v2.score)
  })

  it('pCorrect=1 always emits the reference solution (which passes runTask everywhere)', async () => {
    const b = createMockBackend(1, { pCorrect: 1 })
    for (const task of BENCH_TASKS) {
      const cand = await b.generate(task, { attempt: 0 })
      const code = cand.includes('```') ? cand.split('```')[1].replace(/^js\r?\n/, '').replace(/```\w*$/, '') : cand
      // extract via the same logic used downstream: rely on runTask+extractCodeBlock indirectly
      const v = runTask(code, task)
      expect(v.ok, `reference for ${task.id} failed`).toBe(true)
    }
  })

  it('pCorrect=0 always emits a WRONG candidate (which fails runTask)', async () => {
    const b = createMockBackend(2, { pCorrect: 0 })
    for (const task of sample) {
      const cand = await b.generate(task, { attempt: 0 })
      // Pull the fenced code out using a tiny inline extractor mirroring extractCodeBlock.
      const m = cand.match(/```\s*(?:js|javascript)[ \t]*\r?\n([\s\S]*?)```/i)
      const code = m ? m[1].replace(/\s+$/, '') : cand
      const v = runTask(code, task)
      expect(v.ok).toBe(false)
    }
  })
})

/**
 * The constructive-null regression suite.
 *
 * These tests exist because a 30x5x12 real run produced four identical cell
 * precisions: the generator ignored its context and greedy decoding made every
 * regeneration byte-identical. That made the whole 2x2 causally inert. The
 * tests below pin down both the fix and its negative control.
 */
describe('generate prompt folds in evidence (constructive-null fix)', () => {
  const task = sample[0]

  it('attempt 0 and an informed retry produce DIFFERENT prompts', () => {
    const first = buildGeneratePrompt(task, { attempt: 0 })
    const retry = buildGeneratePrompt(task, {
      attempt: 1,
      envFeedback: { failedCaseIndices: [1], passed: 1, total: 2, errors: ['TypeError: x is not a function'] },
    })
    expect(retry).not.toBe(first)
    expect(retry.length).toBeGreaterThan(first.length)
  })

  it('a retry carrying ONLY a signal differs; a retry carrying nothing does not', () => {
    const first = buildGeneratePrompt(task, { attempt: 0 })
    // No signal at all -> the prompt is unchanged, which is exactly why such a
    // retry cannot change the outcome under greedy decoding. This is the
    // negative control: it MUST stay identical or the guard would be blind.
    expect(buildGeneratePrompt(task, { attempt: 1 })).toBe(first)
    expect(buildGeneratePrompt(task, { attempt: 1, selfCritique: 'returns a string, not a number' })).not.toBe(first)
  })

  it('the environment feedback NEVER leaks expected outputs', () => {
    // Build a genuine failure and turn it into the signal the harness forwards.
    const wrong = createMockBackend(9, { pCorrect: 0 })
    return wrong.generate(task, { attempt: 0 }).then((cand) => {
      const m = cand.match(/```\s*(?:js|javascript)[ \t]*\r?\n([\s\S]*?)```/i)
      const code = m ? m[1] : cand
      const verdict = runTask(code, task)
      expect(verdict.ok).toBe(false)

      const prompt = buildGeneratePrompt(task, {
        attempt: 1,
        envFeedback: {
          failedCaseIndices: verdict.failures.map(f => f.index),
          passed: verdict.passed,
          total: verdict.total,
          errors: verdict.failures.map(f => f.error).filter((x): x is string => typeof x === 'string'),
        },
      })

      // Every expected value of the withheld suite must be absent from the prompt.
      for (const t of task.tests) {
        const serialized = JSON.stringify(t.expected)
        if (serialized === undefined || serialized === 'null')
          continue
        expect(prompt, `leaked expected value ${serialized} for ${task.id}`).not.toContain(serialized)
      }
      expect(prompt).toContain('withheld')
    })
  })
})

describe('mock retry kinematics', () => {
  it('a retry WITH a signal can recover', async () => {
    const b = createMockBackend(5, { pCorrect: 0, pRetrySuccess: 1 })
    const task = sample[0]
    const first = await b.generate(task, { attempt: 0 })
    const retry = await b.generate(task, {
      attempt: 1,
      envFeedback: { failedCaseIndices: [0], passed: 0, total: 2, errors: [] },
    })
    const codeOf = (md: string) => {
      const m = md.match(/```\s*(?:js|javascript)[ \t]*\r?\n([\s\S]*?)```/i)
      return m ? m[1].replace(/\s+$/, '') : md
    }
    expect(runTask(codeOf(first), task).ok).toBe(false)
    expect(runTask(codeOf(retry), task).ok).toBe(true)
  })

  it('a retry WITHOUT a signal cannot recover (the inert-loop control)', async () => {
    const b = createMockBackend(5, { pCorrect: 0, pRetrySuccess: 1 })
    const task = sample[0]
    const retry = await b.generate(task, { attempt: 1 })
    const m = retry.match(/```\s*(?:js|javascript)[ \t]*\r?\n([\s\S]*?)```/i)
    const code = m ? m[1].replace(/\s+$/, '') : retry
    expect(runTask(code, task).ok).toBe(false)
  })
})
