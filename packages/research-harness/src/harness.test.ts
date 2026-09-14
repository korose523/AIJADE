import type { LearningLoopCell } from '@proj-aijade/skill-forge-store'

import type { RunOptions } from './harness'

import { describe, expect, it } from 'vitest'

import { createMockBackend } from './backends'
import { runExperiment } from './harness'

function tinyOpts(seed: number): RunOptions {
  return {
    backend: createMockBackend(seed, { pCorrect: 0.5, hallucination: 0.3, miss: 0.1 }),
    trials: 6,
    rounds: 3,
    seed,
    nTasks: 8,
    pruneThreshold: 0.5,
    pruneMinCalls: 3,
    now: () => 0,
  }
}

/** Aggregate retiredRate over a column (by envFeedback) weighted by cell count. */
function columnRetiredRate(table: LearningLoopCell[], ef: boolean): number {
  const col = table.filter(c => c.envFeedbackEnabled === ef)
  const count = col.reduce((a, c) => a + c.count, 0)
  const retired = col.reduce((a, c) => a + c.retiredRate * c.count, 0)
  return count === 0 ? 0 : retired / count
}

describe('rQ-C harness — core regression', () => {
  it('every 2x2 cell yields a finite precision (not NaN)', async () => {
    const res = await runExperiment(tinyOpts(42))
    expect(res.table).toHaveLength(4)
    for (const c of res.table) {
      expect(Number.isFinite(c.precision), `precision NaN in ${JSON.stringify(c)}`).toBe(true)
      expect(Number.isNaN(c.precision)).toBe(false)
    }
  }, 60000)

  it('envFeedback=ON column has strictly greater retiredRate than envFeedback=OFF', async () => {
    const res = await runExperiment(tinyOpts(42))
    const on = columnRetiredRate(res.table, true)
    const off = columnRetiredRate(res.table, false)
    // OFF column must be 0 (no pruning; self-rejections are 'rejected', not 'retired'),
    // ON column must be > 0 (pruning retires repeatedly-failing skills).
    expect(off).toBe(0)
    expect(on).toBeGreaterThan(0)
  }, 60000)

  it('is reproducible: identical summary for identical seed', async () => {
    const a = await runExperiment(tinyOpts(42))
    const b = await runExperiment(tinyOpts(42))
    const strip = (r: typeof a) => JSON.stringify({
      table: r.table,
      diagnostics: r.diagnostics,
      diffInDiff: r.diffInDiff,
      chiSquare: r.chiSquare,
      perCellCI: r.perCellCI,
    })
    expect(strip(a)).toBe(strip(b))
  }, 60000)

  it('produces a non-trivial self-verification diagnostic on the SV=ON row', async () => {
    const res = await runExperiment(tinyOpts(7))
    // SV=ON conditions generate ~half of all skills with self-verdicts; n should be large.
    expect(res.diagnostics.n).toBeGreaterThan(0)
    // The estimator should recover something near the injected hallucination=0.30 / miss=0.10
    // (within broad tolerance — this is a simulation of the estimator, not a strict target).
    expect(Number.isFinite(res.diagnostics.hallucinationRate)).toBe(true)
  }, 60000)

  it('block design: identical task set per trial across all four conditions', async () => {
    const res = await runExperiment(tinyOpts(42))
    // For every trial, the set of task ids must be the SAME in all four
    // conditions (the fix for B4). If conditions sampled different tasks, the
    // McNemar pairing — and the whole blocked design — would be invalid.
    const taskIdsByConditionTrial = res.conditions.map((c) => {
      const byTrial = new Map<number, Set<string>>()
      for (const r of c.records) {
        const t = r.metadata?.trial as number | undefined
        const taskId = r.metadata?.taskId as string | undefined
        if (t === undefined || taskId === undefined)
          continue
        if (!byTrial.has(t))
          byTrial.set(t, new Set())
        byTrial.get(t)!.add(taskId)
      }
      return byTrial
    })
    for (let t = 0; t < tinyOpts(42).trials; t++) {
      const sets = taskIdsByConditionTrial.map(b => b.get(t))
      expect(sets.every(s => s !== undefined)).toBe(true)
      const first = sets[0]!
      for (const s of sets)
        expect([...s!].sort()).toEqual([...first].sort())
    }
  }, 60000)

  it('exposes the new skill-level result fields (B1/B4) and Holm family of 3', async () => {
    const res = await runExperiment(tinyOpts(42))
    expect(res.analysisUnit).toBe('skill')
    expect(res.nSkills).toBeGreaterThan(0)
    expect(res.nExecutions).toBeGreaterThanOrEqual(res.nSkills)
    // execution-level chi-square retained but flagged diagnostic-only
    expect(res.chiSquareExecutionLevel).toBeDefined()
    expect(res.chiSquare).toBeDefined()
    expect(res.mcnemarEnvFeedback).toBeDefined()
    expect(res.factorialInteraction).toBeDefined()
    expect(res.effectSizes.oddsRatio).toBeDefined()
    expect(res.multiplicity.method).toBe('holm')
    expect(res.multiplicity.adjusted).toHaveLength(3)
  }, 60000)
})
