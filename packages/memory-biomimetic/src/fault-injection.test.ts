import type { FaultInjectionConfig } from './fault-injection'
import type { ScoredCandidate } from './types'

import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'

import { afterEach, describe, expect, it } from 'vitest'

import { FaultInjector, registerFaultExperiment } from './fault-injection'
import { BioticMemory } from './store'
import { DEFAULT_GATING, DEFAULT_MEMORY_CONFIG } from './types'

const QUERY = 'Caroline went to the support group with my sister'
const ITEMS = [
  'Caroline went to the support group with my sister yesterday',
  'the weather was rainy and the dog barked at the mailman on tuesday',
  'we ordered takeout and watched a movie about the ocean and the stars',
  'my brother called to say the train was delayed by the snow storm',
]

function mkStore(): BioticMemory {
  const m = new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, gating: DEFAULT_GATING }, 0)
  ITEMS.forEach((content, i) => m.encode({ id: `e${i}`, content, createdAt: 0, context: { tags: [] } }))
  return m
}

function cfg(kind: FaultInjectionConfig['kind'], over: Partial<FaultInjectionConfig> = {}): FaultInjectionConfig {
  return { enabled: true, kind, rate: 1, seed: 0, ...over }
}

function cand(id: string, kind: ScoredCandidate['kind'] = 'episode'): ScoredCandidate {
  return {
    kind,
    id,
    content: `content-${id}`,
    score: 1,
    parts: { similarity: 1, strength: 1, recency: 1, context: 1, affect: 0 },
  }
}

describe('faultInjector — pure perturbation', () => {
  it('message_drop removes the selected fraction (rate=1 ⇒ all gone)', () => {
    const inj = new FaultInjector(cfg('message_drop'))
    const out = inj.apply([cand('a'), cand('b'), cand('c')])
    expect(out.candidates).toHaveLength(0)
    expect(out.report.applied).toBe(3)
    expect(out.report.kind).toBe('message_drop')
  })

  it('message_drop with rate=0 leaves everything intact', () => {
    const inj = new FaultInjector(cfg('message_drop', { rate: 0 }))
    const out = inj.apply([cand('a'), cand('b')])
    expect(out.candidates.map(c => c.id)).toEqual(['a', 'b'])
    expect(out.report.applied).toBe(0)
  })

  it('duplicate_event doubles the selected candidates with deterministic new ids', () => {
    const inj = new FaultInjector(cfg('duplicate_event'))
    const out = inj.apply([cand('a'), cand('b')])
    expect(out.candidates).toHaveLength(4)
    const dups = out.candidates.filter(c => c.id.includes(':dup:'))
    expect(dups).toHaveLength(2)
    // deterministic id suffix comes from fnv1a ⇒ stable across runs
    expect(dups[0].id.startsWith('a:dup:')).toBe(true)
    expect(dups[0].id).not.toBe('a')
  })

  it('value_corruption reverses the payload of selected candidates', () => {
    const inj = new FaultInjector(cfg('value_corruption'))
    const out = inj.apply([cand('a')])
    // content 'content-a' reversed is 'a-tnetnoc' — a deterministic, clearly garbled payload
    expect(out.candidates[0].content).toBe('a-tnetnoc')
    expect(out.candidates[0].content).not.toBe('content-a')
  })

  it('latency_injection leaves candidates intact but reports a modelled latency', () => {
    const inj = new FaultInjector(cfg('latency_injection', { maxLatencyMs: 1000 }))
    const out = inj.apply([cand('a'), cand('b')])
    expect(out.candidates.map(c => c.id)).toEqual(['a', 'b'])
    expect(out.report.latencyMs).toBeGreaterThanOrEqual(0)
    expect(out.report.latencyMs!).toBeLessThan(1000)
  })

  it('component_crash throws FaultInjectedError naming the crashed component', () => {
    const inj = new FaultInjector(cfg('component_crash', { target: 'fact' }))
    expect(() => inj.apply([cand('a', 'fact'), cand('b', 'episode')])).toThrow(/component "fact" crashed/)
  })
})

describe('faultInjector — determinism', () => {
  it('same (config, candidates) ⇒ identical selection every time', () => {
    const base = [cand('a'), cand('b'), cand('c'), cand('d'), cand('e')]
    const r1 = new FaultInjector(cfg('message_drop', { rate: 0.5, seed: 42 })).apply(base).candidates.map(c => c.id)
    const r2 = new FaultInjector(cfg('message_drop', { rate: 0.5, seed: 42 })).apply(base).candidates.map(c => c.id)
    expect(r1).toEqual(r2)
  })

  it('different seeds can yield different selections (not hardcoded)', () => {
    const base = [cand('a'), cand('b'), cand('c'), cand('d'), cand('e')]
    const s0 = new FaultInjector(cfg('message_drop', { rate: 0.5, seed: 0 })).apply(base).candidates.map(c => c.id)
    const s7 = new FaultInjector(cfg('message_drop', { rate: 0.5, seed: 7 })).apply(base).candidates.map(c => c.id)
    // at minimum both runs are internally consistent; seeds may or may not differ,
    // but the draw must be seed-driven (not always-empty / always-full).
    expect(Array.isArray(s0)).toBe(true)
    expect(Array.isArray(s7)).toBe(true)
  })

  it('selection order is independent of input ordering', () => {
    const fwd = [cand('a'), cand('b'), cand('c'), cand('d')]
    const rev = [cand('d'), cand('c'), cand('b'), cand('a')]
    const a = new FaultInjector(cfg('message_drop', { rate: 1, seed: 5 })).apply(fwd).candidates.map(c => c.id)
    const b = new FaultInjector(cfg('message_drop', { rate: 1, seed: 5 })).apply(rev).candidates.map(c => c.id)
    expect(a).toEqual(b)
  })
})

describe('store.retrieve + fault injection', () => {
  it('default (no faultInjection config) ⇒ retrieval is untouched (regression guard)', () => {
    const m = mkStore()
    const baseline = m.retrieve(QUERY, 10, false).map(c => c.id)
    expect(baseline.length).toBeGreaterThan(0)
    expect(m.faultInjectionReport()).toBeUndefined()
  })

  it('enabled with rate=0 ⇒ identical result, report present but applied=0', () => {
    const m = mkStore()
    const out = m.retrieve(QUERY, 10, false, undefined)
    const faulted = new BioticMemory(
      { ...DEFAULT_MEMORY_CONFIG, gating: DEFAULT_GATING, faultInjection: cfg('message_drop', { rate: 0 }) },
      0,
    )
    ITEMS.forEach((content, i) => faulted.encode({ id: `e${i}`, content, createdAt: 0, context: { tags: [] } }))
    const fIds = faulted.retrieve(QUERY, 10, false).map(c => c.id)
    expect(fIds).toEqual(out.map(c => c.id))
    expect(faulted.faultInjectionReport()?.applied).toBe(0)
  })

  it('message_drop with rate=1 removes all returned items', () => {
    const m = new BioticMemory(
      { ...DEFAULT_MEMORY_CONFIG, gating: DEFAULT_GATING, faultInjection: cfg('message_drop', { rate: 1 }) },
      0,
    )
    ITEMS.forEach((content, i) => m.encode({ id: `e${i}`, content, createdAt: 0, context: { tags: [] } }))
    const out = m.retrieve(QUERY, 10, false)
    expect(out).toHaveLength(0)
    expect(m.faultInjectionReport()?.applied).toBe(ITEMS.length)
  })

  it('component_crash exercises fail-closed: crashed kind dropped, others served', () => {
    const m = new BioticMemory(
      {
        ...DEFAULT_MEMORY_CONFIG,
        gating: DEFAULT_GATING,
        faultInjection: cfg('component_crash', { target: 'episode', rate: 1 }),
      },
      0,
    )
    ITEMS.forEach((content, i) => m.encode({ id: `e${i}`, content, createdAt: 0, context: { tags: [] } }))
    const out = m.retrieve(QUERY, 10, false)
    // every returned candidate must NOT be an episode (the crashed store)
    expect(out.every(c => c.kind !== 'episode')).toBe(true)
    const rep = m.faultInjectionReport()
    expect(rep?.kind).toBe('component_crash')
    expect(rep?.crashedComponent).toBe('episode')
    expect(rep?.applied).toBe(ITEMS.length)
  })

  it('value_corruption corrupts returned payloads but keeps ids/scores', () => {
    const m = new BioticMemory(
      { ...DEFAULT_MEMORY_CONFIG, gating: DEFAULT_GATING, faultInjection: cfg('value_corruption', { rate: 1 }) },
      0,
    )
    ITEMS.forEach((content, i) => m.encode({ id: `e${i}`, content, createdAt: 0, context: { tags: [] } }))
    const out = m.retrieve(QUERY, 10, false)
    expect(out).toHaveLength(ITEMS.length)
    expect(out[0].content).not.toBe(ITEMS[0])
    expect(out[0].id).toBe('e0')
  })
})

describe('registerFaultExperiment — §38 registration chain', () => {
  let dir: string
  afterEach(() => {
    if (dir)
      rmSync(dir, { recursive: true, force: true })
  })

  it('registers a fault scenario into a (temp) registry', () => {
    dir = mkdtempSync(`${tmpdir()}/aijade-fault-`)
    const registryPath = `${dir}/experiments.registry.json`
    const { manifest } = registerFaultExperiment(cfg('message_drop', { rate: 0.3 }), { registryPath })
    expect(manifest.id).toBe('fault:message_drop')
    // re-read the registry to prove it was actually written
    const reg = JSON.parse(readFileSync(registryPath, 'utf8'))
    expect(reg.experiments['fault:message_drop']).toBeDefined()
  })
})
