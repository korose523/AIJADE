import { BENCH_TASKS, extractCodeBlock, runTask } from '@proj-aijade/skill-bench-env'

import { createOllamaBackend } from './src/backends'

const HARD = ['parse-query-string', 'arr-remove-falsy', 'obj-get-nested', 'arr-intersection', 'parse-version']
const backend = createOllamaBackend({ model: 'qwen2.5-coder:7b-instruct', sampling: { temperature: 0, seed: 42 } })

for (const id of HARD) {
  const task = BENCH_TASKS.find(t => t.id === id)!
  const a0 = await backend.generate(task, { attempt: 0 })
  const c0 = extractCodeBlock(a0) ?? a0
  const v0 = runTask(c0, task)

  const signal = {
    failedCaseIndices: v0.failures.map(f => f.index),
    passed: v0.passed,
    total: v0.total,
    errors: v0.failures.map(f => f.error).filter((x): x is string => typeof x === 'string'),
  }
  const a1 = await backend.generate(task, { attempt: 1, envFeedback: signal, previousCode: c0 })
  const c1 = extractCodeBlock(a1) ?? a1
  const v1 = runTask(c1, task)

  console.log(`\n=== ${id} ===`)
  console.log(`  attempt0        ok=${v0.ok} passed=${v0.passed}/${v0.total}`)
  console.log(`  attempt1+prev   ok=${v1.ok} passed=${v1.passed}/${v1.total}`)
  console.log(`  code changed:   ${c0.trim() !== c1.trim()}`)
  if (!v0.ok && v1.ok)
    console.log('  >>> RECOVERED')
  else if (c0.trim() === c1.trim())
    console.log('  xx identical re-emission')
}
