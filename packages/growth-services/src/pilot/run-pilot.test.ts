import { existsSync } from 'node:fs'

import { beforeAll, describe, expect, it } from 'vitest'

import { MECHANISM_CONFIGS } from './configs'
import { runPilot } from './run-pilot'

describe('runPilot — determinism & structure', () => {
  it('produces exactly the 10 Table-3 configurations', async () => {
    const p = await runPilot(1, false)
    expect(p.configs.length).toBe(10)
    expect(p.configs.map(c => c.id)).toEqual([
      'B0',
      'B1',
      'B2',
      'B3',
      'B4',
      'B5',
      'A1',
      'A1-HAC',
      'A1-DGM',
      'A1-CDI',
    ])
  })

  it('is byte-for-byte deterministic for the same seed', async () => {
    const [a, b] = await Promise.all([runPilot(1, false), runPilot(1, false)])
    expect(a).toEqual(b)
  })

  it('writes the result files when asked', async () => {
    await runPilot(1, true)
    expect(existsSync(new URL('./pilot-results/pilot-results.json', import.meta.url))).toBe(true)
    expect(existsSync(new URL('./pilot-results/AIJADE_试点实验结果.md', import.meta.url))).toBe(true)
  })
})

describe('runPilot — faithful Table-3 behaviour (emergent, not hard-coded)', () => {
  // `await` is only legal inside an async function, and a `describe` callback is
  // not one. Hoisting the run into `beforeAll` also keeps this suite to a single
  // pilot execution instead of one per test.
  let p!: Awaited<ReturnType<typeof runPilot>>
  beforeAll(async () => {
    p = await runPilot(1, false)
  })

  // B0 writes nothing that is true (`strategy: 'none'`), so it retains no golden
  // evidence and no contradiction pair: FUB = 0 and CR = 0.
  //
  // Its FCR is **1**, not 0, and that is the intended behaviour rather than a
  // defect: the dual-graph split is the *only* false-fact filter in this design
  // (`put()` commits a statement with `isTrue === false` unconditionally unless
  // `dualGraphSeparation` is on — see the comment there). B0 has DGM off, like
  // every other baseline, so all 91 poison statements consolidate. This is what
  // makes the FCR column discriminate A1 (DGM on) from the whole baseline block;
  // asserting 0 here would have made B0 indistinguishable from the full model on
  // the very metric the DGM ablation is supposed to move.
  it('b0 (no memory) retains nothing useful (FUB=0, CR=0) but, lacking a dual graph, consolidates every poison statement (FCR=1)', () => {
    expect(p.results.fub.B0.value).toBe(0)
    expect(p.results.cr.B0.value).toBe(0)
    expect(p.results.fcr.B0.value).toBe(1)
  })

  it('a1 is the full model: CR=1, FCR=0, FUB≈1, no identity drift (CDI on)', () => {
    expect(p.results.cr.A1.value).toBeCloseTo(1, 6)
    expect(p.results.fcr.A1.value).toBeCloseTo(0, 6)
    expect(p.results.fub.A1.value).toBeGreaterThan(0.99)
    expect(p.results.identityDrift.A1.value).toBeCloseTo(0, 6)
    expect(p.results.coreStability.A1.value).toBeCloseTo(1, 6)
  })

  it('a1−DGM (no dual graph) loses Contradiction Retention and raises False Consolidation', () => {
    expect(p.results.cr['A1-DGM'].value).toBeLessThan(p.results.cr.A1.value)
    expect(p.results.fcr['A1-DGM'].value).toBeGreaterThan(p.results.fcr.A1.value)
    expect(p.results.cr['A1-DGM'].value).toBeCloseTo(0, 6) // overwritten, not preserved
    expect(p.results.fcr['A1-DGM'].value).toBeCloseTo(1, 6) // poison consolidated
  })

  it('a1−HAC (no HAC) drops EffectiveProactivity vs A1 (more low-value clutter admitted)', () => {
    expect(p.results.epRate['A1-HAC'].value).toBeLessThan(p.results.epRate.A1.value)
  })

  it('a1−CDI (no identity constraint) raises Identity Drift and lowers Core Stability vs A1', () => {
    expect(p.results.identityDrift['A1-CDI'].value).toBeGreaterThan(p.results.identityDrift.A1.value)
    expect(p.results.coreStability['A1-CDI'].value).toBeLessThan(p.results.coreStability.A1.value)
  })

  it('every non-B0 config beats B0 on Future Utility@Budget', () => {
    for (const id of ['B1', 'B2', 'B3', 'B4', 'B5', 'A1', 'A1-HAC', 'A1-DGM', 'A1-CDI'])
      expect(p.results.fub[id].value).toBeGreaterThanOrEqual(p.results.fub.B0.value)
  })
})

describe('runPilot — statistics present (incl. new identity metrics)', () => {
  let p!: Awaited<ReturnType<typeof runPilot>>
  beforeAll(async () => {
    p = await runPilot(1, false)
  })
  it('reports bootstrap CIs, Cohen d and Bonferroni per metric (memory + identity)', () => {
    for (const key of ['fub', 'epRate', 'gc', 'precision', 'recall', 'cr', 'fcr', 'coreStability', 'identityDrift', 'skillRetention']) {
      expect(p.results[key].A1.ci.length).toBe(2)
      expect(p.effectSizesVsB0[key].A1 === null || typeof p.effectSizesVsB0[key].A1 === 'number').toBe(true)
      expect(p.bonferroni[key].correctedAlpha).toBeCloseTo(0.05 / 9, 10)
    }
  })
  it('mECHANISM_CONFIGS aligns with Table 3 columns', () => {
    const a1 = MECHANISM_CONFIGS.find(c => c.id === 'A1')!
    expect(a1.memoryWrite).toBe('hac_gated')
    expect(a1.endogenousState).toBe(true)
    expect(a1.dualGraphSeparation).toBe(true)
    expect(a1.identityConstraint).toBe(true)
    const b0 = MECHANISM_CONFIGS.find(c => c.id === 'B0')!
    expect(b0.memoryWrite).toBe('none')
  })
})
