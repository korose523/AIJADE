import { BENCH_TASKS, runTask } from '@proj-aijade/skill-bench-env'
import { describe, expect, it } from 'vitest'

import { createMockBackend } from './backends'

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
