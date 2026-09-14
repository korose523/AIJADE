import { describe, expect, it } from 'vitest'

import { BENCH_TASKS, runTask } from './sandbox'
import { REFERENCE_SOLUTIONS, WRONG_CANDIDATES } from './solutions'

describe('rEFERENCE_SOLUTIONS integrity', () => {
  it('covers every BENCH_TASKS id', () => {
    const ids = new Set(BENCH_TASKS.map(t => t.id))
    expect(ids.size).toBe(BENCH_TASKS.length) // ids are unique
    for (const id of ids) {
      expect(REFERENCE_SOLUTIONS[id], `missing reference for "${id}"`).toBeDefined()
      expect(typeof REFERENCE_SOLUTIONS[id]).toBe('string')
    }
  })

  it('every reference solution passes its task\'s full test suite via runTask', () => {
    for (const task of BENCH_TASKS) {
      const code = REFERENCE_SOLUTIONS[task.id]
      expect(code, `no reference for ${task.id}`).toBeDefined()
      const v = runTask(code, task)
      expect(v.ok, `reference for "${task.id}" failed: ${JSON.stringify(v.failures)}`).toBe(true)
    }
  })
})

describe('wRONG_CANDIDATES are runnable but always fail', () => {
  it('each wrong candidate fails every task\'s test suite', () => {
    for (const wrong of WRONG_CANDIDATES) {
      for (const task of BENCH_TASKS) {
        const v = runTask(wrong, task)
        expect(v.ok, `wrong candidate "${wrong}" unexpectedly passed "${task.id}"`).toBe(false)
      }
    }
  })
})
