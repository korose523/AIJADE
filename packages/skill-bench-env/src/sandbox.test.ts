import type { BenchTask } from './types'

import { describe, expect, it } from 'vitest'

import { BENCH_TASKS, extractCodeBlock, runTask, sampleTasks } from './sandbox'

function taskById(id: string): BenchTask {
  const t = BENCH_TASKS.find(x => x.id === id)
  if (!t)
    throw new Error(`missing task ${id}`)
  return t
}

describe('extractCodeBlock', () => {
  it('extracts the first js fence, trims trailing fence', () => {
    const md = 'Here you go:\n```js\nfunction solve(a){ return a }\n```\nDone.'
    expect(extractCodeBlock(md)).toBe('function solve(a){ return a }')
  })

  it('is case-insensitive on the language tag', () => {
    const md = '```JavaScript\nfunction solve(){ return 1 }\n```'
    expect(extractCodeBlock(md)).toBe('function solve(){ return 1 }')
  })

  it('handles a language tag followed by a newline', () => {
    const md = '```js\nreturn 42\n```'
    expect(extractCodeBlock(md)).toBe('return 42')
  })

  it('handles indentation before the fence', () => {
    const md = '  ```js\n  const solve = x => x\n  ```'
    expect(extractCodeBlock(md)).toBe('  const solve = x => x')
  })

  it('takes the FIRST code block when several are present', () => {
    const md = '```js\nconst a = 1\n```\ntext\n```js\nconst b = 2\n```'
    expect(extractCodeBlock(md)).toBe('const a = 1')
  })

  it('returns the whole string when no fence is present', () => {
    expect(extractCodeBlock('function solve(){ return 7 }')).toBe('function solve(){ return 7 }')
  })

  it('returns undefined for nullish input', () => {
    expect(extractCodeBlock(undefined as unknown as string)).toBeUndefined()
  })
})

describe('runTask — happy / unhappy paths', () => {
  const sumTask = taskById('arr-sum')

  it('correct solution -> ok true, all passed', () => {
    const code = 'function solve(nums){ return nums.reduce((s, x) => s + x, 0) }'
    const v = runTask(code, sumTask)
    expect(v.ok).toBe(true)
    expect(v.passed).toBe(sumTask.tests.length)
    expect(v.total).toBe(sumTask.tests.length)
    expect(v.failures).toHaveLength(0)
  })

  it('incorrect solution -> ok false with failures recorded', () => {
    const code = 'function solve(nums){ return nums.reduce((s, x) => s + x, 0) + 1 }' // off-by-one
    const v = runTask(code, sumTask)
    expect(v.ok).toBe(false)
    expect(v.failures.length).toBeGreaterThan(0)
    expect(v.failures[0]).toHaveProperty('expected')
    expect(v.failures[0]).toHaveProperty('actual')
  })

  it('syntax error -> error filled, does not throw', () => {
    const code = 'function solve( { bad'
    const v = runTask(code, sumTask)
    expect(v.ok).toBe(false)
    expect(typeof v.error).toBe('string')
    expect(v.error!.length).toBeGreaterThan(0)
  })

  it('thrown exception -> failure recorded, does not throw', () => {
    const code = 'function solve(){ throw new Error(\'boom\') }'
    const v = runTask(code, sumTask)
    expect(v.ok).toBe(false)
    expect(v.failures.length).toBeGreaterThan(0)
    expect(v.failures[0].error).toMatch(/boom/)
  })

  it('timeout -> error filled, does not hang or throw', () => {
    const code = 'function solve(){ while (true) {} }'
    const timeoutTask: BenchTask = { ...sumTask, timeoutMs: 200 }
    const v = runTask(code, timeoutTask)
    expect(v.ok).toBe(false)
    expect(typeof v.error).toBe('string')
    expect(v.error).toMatch(/timed out|timeout/i)
  })

  it('no callable function -> reports clearly, does not throw', () => {
    const code = 'const notAFunction = 42;'
    const v = runTask(code, sumTask)
    expect(v.ok).toBe(false)
    expect(v.error).toMatch(/no callable function/)
  })
})

describe('sandbox escape protection', () => {
  const escapeTask: BenchTask = {
    id: '__escape__',
    instruction: '',
    category: 'logic',
    tier: 'easy',
    tests: [{ args: [], expected: { r: 'undefined', p: 'undefined', f: 'undefined' } }],
  }

  it('cannot read require / process / fs from the sandbox', () => {
    const code = 'function solve(){ return { r: typeof require, p: typeof process, f: typeof fs } }'
    const v = runTask(code, escapeTask)
    expect(v.ok).toBe(true)
  })

  it('throws a ReferenceError when a host global is accessed directly', () => {
    const code = 'function solve(){ return process }'
    const v = runTask(code, escapeTask)
    expect(v.ok).toBe(false)
    expect(v.failures[0].error).toMatch(/process/)
  })
})

describe('sampleTasks', () => {
  it('is deterministic for the same seed', () => {
    const a = sampleTasks(10, 1234)
    const b = sampleTasks(10, 1234)
    expect(a.map(t => t.id)).toEqual(b.map(t => t.id))
  })

  it('produces different subsets for different seeds', () => {
    const a = sampleTasks(12, 1)
    const b = sampleTasks(12, 2)
    expect(a.map(t => t.id)).not.toEqual(b.map(t => t.id))
  })

  it('is duplicate-free', () => {
    const ids = sampleTasks(40, 99).map(t => t.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('never returns more than requested or more than exist', () => {
    expect(sampleTasks(1000, 7)).toHaveLength(BENCH_TASKS.length)
    expect(sampleTasks(5, 7)).toHaveLength(5)
  })
})
