import type { InterventionPlan } from './intervention'

import { rmSync } from 'node:fs'
import { join } from 'node:path'

import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import { readRegistry } from './experiment'
import {
  ALL_ABLATION_PLANS,
  BASELINE_PLANS,
  bypassOf,
  CDI_ABLATION_PLANS,
  DEFAULT_SWITCHES,
  DGM_ABLATION_PLANS,
  HAC_ABLATION_PLANS,
  INTERVENTION_POINTS,

  interventionRng,
  isEnabled,
  registerIntervention,
  resolveIntervention,
  validateInterventionPlan,
} from './intervention'

const REG = join(process.cwd(), 'eval', '.intervention-test.registry.json')

/**
 * Best-effort, fault-tolerant cleanup of the registry file.
 *
 * `rmSync(path, { force: true })` only suppresses ENOENT — in restricted
 * sandboxes it still throws EPERM / ENOTEMPTY, which would abort the suite.
 * Cleanup must never fail the tests, so we swallow those codes (the leftover
 * file does not affect any assertion: the suite writes then re-reads REG).
 * Unexpected errors are still re-thrown so real problems stay visible.
 */
function safeRmSync(path: string): void {
  try {
    rmSync(path, { force: true, recursive: true })
  }
  catch (err) {
    const code = (err as NodeJS.ErrnoException | undefined)?.code
    // In restricted sandboxes `rmSync` can still throw EPERM / ENOTEMPTY even
    // with `force: true` (force only suppresses ENOENT). Cleanup is best-effort
    // and must never fail the suite, so those codes are swallowed. Unexpected
    // errors are re-thrown so real problems stay visible.
    if (code === 'EPERM' || code === 'ENOTEMPTY' || code === 'EACCES')
      return
    throw err
  }
}

function plan(over: Partial<InterventionPlan> = {}): InterventionPlan {
  return {
    id: 'test-abl',
    name: 'Test ablation',
    description: 'turns something off',
    switches: { hac_active_replay: false },
    ...over,
  }
}

beforeAll(() => safeRmSync(REG))
afterAll(() => safeRmSync(REG))

describe('iNTERVENTION_POINTS — 单一权威清单', () => {
  it('covers §38.1–38.4 with unique ids and defaults', () => {
    const ids = INTERVENTION_POINTS.map(p => p.id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(INTERVENTION_POINTS.length).toBeGreaterThanOrEqual(20)
    for (const g of ['memory_baseline', 'hac', 'dgm', 'cdi'])
      expect(INTERVENTION_POINTS.some(p => p.group === g)).toBe(true)
  })

  it('defaults to the full mechanism: dual graph on, anti-patterns off', () => {
    expect(DEFAULT_SWITCHES.dgm_dual_graph).toBe(true)
    expect(DEFAULT_SWITCHES.dgm_counter_evidence).toBe(true)
    expect(DEFAULT_SWITCHES.cdi_shadow_eval).toBe(true)
    expect(DEFAULT_SWITCHES.dgm_llm_commit).toBe(false)
    expect(DEFAULT_SWITCHES.hac_fix_transition).toBe(false)
    expect(DEFAULT_SWITCHES.hac_random_write).toBe(false)
  })
})

describe('validateInterventionPlan', () => {
  it('accepts a plan that changes at least one known switch', () => {
    expect(validateInterventionPlan(plan())).toEqual({ ok: true })
  })

  it('rejects an empty switch map (an ablation must ablate something)', () => {
    const r = validateInterventionPlan(plan({ switches: {} }))
    expect(r.ok).toBe(false)
    if (!r.ok)
      expect(r.reason).toMatch(/≥1 switch/)
  })

  it('rejects an unknown intervention point (no silent typo drift)', () => {
    const r = validateInterventionPlan(plan({ switches: { hac_active_replayy: false } }))
    expect(r.ok).toBe(false)
    if (!r.ok)
      expect(r.reason).toMatch(/Unknown intervention point/)
  })

  it('rejects an unknown bypass point', () => {
    const r = validateInterventionPlan(plan({ bypass: { not_a_point: 'x' } }))
    expect(r.ok).toBe(false)
    if (!r.ok)
      expect(r.reason).toMatch(/Unknown bypass point/)
  })

  it('rejects a plan with no id', () => {
    expect(validateInterventionPlan(plan({ id: '' })).ok).toBe(false)
  })
})

describe('resolveIntervention — 有效开关图 + 指纹', () => {
  it('merges overrides onto the defaults', () => {
    const r = resolveIntervention(plan({ switches: { hac_active_replay: false } }))
    expect(r.switches.hac_active_replay).toBe(false)
    expect(r.switches.hac_state).toBe(true) // 未覆写 ⇒ 保持默认
    expect(Object.keys(r.switches).length).toBe(INTERVENTION_POINTS.length)
  })

  it('is deterministic: same (plan, seed) ⇒ same fingerprint', () => {
    const a = resolveIntervention(plan(), 7)
    const b = resolveIntervention(plan(), 7)
    expect(a.fingerprint).toBe(b.fingerprint)
  })

  it('gives different fingerprints for different seeds and different plans', () => {
    expect(resolveIntervention(plan(), 7).fingerprint).not.toBe(resolveIntervention(plan(), 8).fingerprint)
    const other = plan({ id: 'other', switches: { hac_state: false } })
    expect(resolveIntervention(plan(), 7).fingerprint).not.toBe(resolveIntervention(other, 7).fingerprint)
  })

  it('does not depend on key insertion order', () => {
    const a = resolveIntervention(plan({ switches: { hac_state: false, hac_active_replay: false } }))
    const b = resolveIntervention(plan({ switches: { hac_active_replay: false, hac_state: false } }))
    expect(a.fingerprint).toBe(b.fingerprint)
  })

  it('throws on an invalid plan or a non-finite seed', () => {
    expect(() => resolveIntervention(plan({ switches: {} }))).toThrow(/invalid/)
    expect(() => resolveIntervention(plan(), Number.NaN)).toThrow(/finite seed/)
  })
})

describe('isEnabled / bypassOf', () => {
  it('reports effective state and treats an unknown point as disabled', () => {
    const r = resolveIntervention(plan({ switches: { hac_active_replay: false } }))
    expect(isEnabled(r, 'hac_active_replay')).toBe(false)
    expect(isEnabled(r, 'hac_state')).toBe(true)
    expect(isEnabled(r, 'nope')).toBe(false)
  })

  it('exposes the bypass replacement', () => {
    const r = resolveIntervention(plan({ bypass: { long_term_memory: 'window(8)' } }))
    expect(bypassOf(r, 'long_term_memory')).toBe('window(8)')
    expect(bypassOf(r, 'hac_state')).toBeUndefined()
  })
})

describe('interventionRng — 固定种子的随机消融', () => {
  it('is deterministic for a given seed and differs across seeds', () => {
    const a = interventionRng(42)
    const b = interventionRng(42)
    const c = interventionRng(43)
    const seqA = [a(), a(), a()]
    const seqB = [b(), b(), b()]
    const seqC = [c(), c(), c()]
    expect(seqA).toEqual(seqB)
    expect(seqA).not.toEqual(seqC)
    for (const v of seqA) {
      expect(v).toBeGreaterThanOrEqual(0)
      expect(v).toBeLessThan(1)
    }
  })
})

describe('§38 预置基线与消融计划', () => {
  it('ships B0–B5 and A1 baselines', () => {
    expect(BASELINE_PLANS.map(p => p.id)).toEqual(['B0', 'B1', 'B2', 'B3', 'B4', 'B5', 'A1'])
  })

  it('ships the HAC / DGM / CDI ablation sets', () => {
    expect(HAC_ABLATION_PLANS.length).toBeGreaterThanOrEqual(7)
    expect(DGM_ABLATION_PLANS.some(p => p.id === 'dgm-llm-commit')).toBe(true)
    expect(CDI_ABLATION_PLANS.some(p => p.id === 'cdi-full')).toBe(true)
  })

  it('every shipped plan is internally valid and resolves', () => {
    for (const p of ALL_ABLATION_PLANS) {
      expect(validateInterventionPlan(p).ok).toBe(true)
      expect(resolveIntervention(p).fingerprint).toMatch(/^[0-9a-f]{8}$/)
    }
  })

  it('b0 really removes long-term memory', () => {
    const b0 = resolveIntervention(BASELINE_PLANS[0])
    expect(isEnabled(b0, 'long_term_memory')).toBe(false)
  })
})

describe('registerIntervention — 消融被登记', () => {
  it('writes a §38 ExperimentManifest condition into the registry', () => {
    const { manifest, resolved } = registerIntervention(plan(), { seed: 3, registryPath: REG })
    expect(manifest.id).toBe('intervention:test-abl')
    expect(manifest.schema).toBe('aijade.experiment_manifest@1')
    expect(manifest.seed).toBe(3)
    expect(manifest.conditions[0].name).toBe('test-abl')
    expect(manifest.metrics.length).toBeGreaterThan(0)
    expect(resolved.fingerprint).toMatch(/^[0-9a-f]{8}$/)
  })

  it('re-reading the registry shows the intervention was registered', () => {
    const reg = readRegistry(REG)
    expect(reg.experiments['intervention:test-abl']).toBeDefined()
  })
})
