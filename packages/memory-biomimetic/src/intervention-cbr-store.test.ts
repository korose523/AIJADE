import type { ReplayBundle } from './cbr'

import { rmSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { REPLAY_BUNDLE_SCHEMA } from './cbr'
import { BASELINE_PLANS, DEFAULT_SWITCHES } from './intervention'
import { InMemoryStorageAdapter } from './storage'
import { BioticMemory } from './store'
import { DEFAULT_MEMORY_CONFIG } from './types'

const B0 = BASELINE_PLANS.find(p => p.id === 'B0')!
const A1 = BASELINE_PLANS.find(p => p.id === 'A1')!
const B1 = BASELINE_PLANS.find(p => p.id === 'B1')!

/**
 * Best-effort, fault-tolerant cleanup of a registry file.
 *
 * `rmSync(path, { force: true })` only suppresses ENOENT — in restricted
 * sandboxes it still throws EPERM / ENOTEMPTY, which would abort the suite.
 * Cleanup must never fail the tests, so we swallow those codes (a leftover
 * registry file does not affect any assertion here). Unexpected errors are
 * still re-thrown so real problems stay visible.
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

const STATE_KEYS = ['a', 'v', 'd', 'n', 's', 'c', 'b']
function state(fill: number): Record<string, number> {
  return Object.fromEntries(STATE_KEYS.map(k => [k, fill]))
}
function bundle(over: Partial<ReplayBundle> = {}): ReplayBundle {
  return {
    schema: REPLAY_BUNDLE_SCHEMA,
    bundleId: 'b1',
    event_ids: ['e1', 'e2'],
    state_before: state(0.2),
    memory_ids_retrieved: ['m1'],
    prompt_digest: 'sha256:abc',
    model_manifest: { model: 'qwythos:latest', sampling: { temperature: 0 } },
    action_plan: ['retrieve', 'answer'],
    tool_results: [{ ok: true }],
    speech_timeline: [{ t: 0, text: 'the answer is four' }],
    semantic_motion: [{ t: 0, motion: 'nod' }],
    user_feedback: { valence: 0.5, signal: 'F' },
    state_after: state(0.6),
    ...over,
  }
}

function interventionConfig() {
  return { ...DEFAULT_MEMORY_CONFIG, intervention: { enabled: true } }
}

describe('§38 intervention API in store (opt-in, H2c-compatible)', () => {
  it('is absent unless enabled — baseline queries fall back to DEFAULT_SWITCHES', () => {
    const m = new BioticMemory()
    expect(m.interventionFingerprint()).toBeUndefined()
    expect(m.interventionEnabled('long_term_memory')).toBe(DEFAULT_SWITCHES.long_term_memory)
    expect(m.applyIntervention(B0)).toBeUndefined()
  })

  it('resolved state drives interventionEnabled after applyIntervention', () => {
    const m = new BioticMemory(interventionConfig())
    expect(m.interventionFingerprint()).toBeUndefined()
    const r = m.applyIntervention(B0)!
    expect(r.resolved).toBeDefined()
    expect(r.registered).toBeUndefined() // no registryPath ⇒ no disk write
    expect(m.interventionFingerprint()).toBe(r.resolved.fingerprint)
    // B0 flips long_term_memory off, leaves other defaults intact
    expect(m.interventionEnabled('long_term_memory')).toBe(false)
    expect(m.interventionEnabled('salience_threshold')).toBe(true)
  })

  it('re-applying a full-mechanism plan restores default-on switches', () => {
    const m = new BioticMemory(interventionConfig())
    m.applyIntervention(B0)
    expect(m.interventionEnabled('long_term_memory')).toBe(false)
    m.applyIntervention(A1)
    expect(m.interventionEnabled('long_term_memory')).toBe(true)
    expect(m.interventionEnabled('hac_state')).toBe(true)
    expect(m.interventionEnabled('hac_random_write')).toBe(false)
  })

  it('exposes the bypass tag for a bypassed point', () => {
    const m = new BioticMemory(interventionConfig())
    m.applyIntervention(B1)
    expect(m.interventionBypass('long_term_memory')).toBe('window(8)')
  })

  it('persists the resolved intervention across rehydration (§26 + §38)', () => {
    const adapter = new InMemoryStorageAdapter()
    const m1 = new BioticMemory({ ...interventionConfig(), storage: adapter })
    const fp = m1.applyIntervention(B0)!.resolved.fingerprint

    const m2 = new BioticMemory({ ...interventionConfig(), storage: adapter })
    expect(m2.interventionFingerprint()).toBe(fp)
    expect(m2.interventionEnabled('long_term_memory')).toBe(false)
  })

  it('optionally registers the intervention as an ExperimentManifest (writes registry)', () => {
    const reg = join(process.cwd(), 'eval', '.store-intervention.registry.json')
    safeRmSync(reg)
    const m = new BioticMemory(interventionConfig())
    const r = m.applyIntervention(B0, { registryPath: reg })!
    expect(r.registered?.manifest.id).toBe('intervention:B0')
    safeRmSync(reg)
  })
})

describe('§12 CBR in store (opt-in, P8/§43 decoupled)', () => {
  it('is absent unless enabled', () => {
    const m = new BioticMemory()
    expect(m.cbrLogBundle(bundle())).toBeUndefined()
    expect(m.cbrBundles()).toEqual([])
  })

  it('logs replay bundles, rejects duplicates and invalid bundles (append-only evidence)', () => {
    const m = new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, cbr: { enabled: true } })
    expect(m.cbrLogBundle(bundle())?.ok).toBe(true)
    expect(m.cbrLogBundle(bundle())?.ok).toBe(false) // duplicate bundleId rejected
    expect(m.cbrLogBundle(bundle({ bundleId: 'b2', event_ids: [], state_after: state(0.1) }))?.ok).toBe(false)
    expect(m.cbrBundles()).toHaveLength(1)
    expect(m.cbrGetBundle('b1')?.bundleId).toBe('b1')
    expect(m.cbrGetBundle('missing')).toBeUndefined()
  })

  it('estimates a paired ITE over logged bundles', () => {
    const m = new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, cbr: { enabled: true } })
    m.cbrLogBundle(bundle({ bundleId: 'b1' }))
    m.cbrLogBundle(bundle({ bundleId: 'b2' }))
    // treated(gate=1) clearly beats control(gate=0) on both bundles
    const big = m.cbrEstimateITE({ b1: 1, b2: 1 }, { b1: 0, b2: 0 })!
    expect(big.n).toBe(2)
    expect(big.significant).toBe(true)
    expect(big.mean).toBeCloseTo(1, 6)
    // near-zero effect ⇒ CI crosses 0 ⇒ not significant
    const zero = m.cbrEstimateITE({ b1: 0.5, b2: 0.5 }, { b1: 0.5, b2: 0.5 })!
    expect(zero.n).toBe(2)
    expect(zero.significant).toBe(false)
  })

  it('persists logged bundles across rehydration (§26 + §12)', () => {
    const adapter = new InMemoryStorageAdapter()
    const m1 = new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, cbr: { enabled: true }, storage: adapter })
    m1.cbrLogBundle(bundle({ bundleId: 'b1' }))
    m1.cbrLogBundle(bundle({ bundleId: 'b2' }))

    const m2 = new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, cbr: { enabled: true }, storage: adapter })
    expect(m2.cbrBundles()).toHaveLength(2)
    expect(m2.cbrGetBundle('b1')?.bundleId).toBe('b1')
  })
})
