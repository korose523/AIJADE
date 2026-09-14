import type { ExperimentManifest } from './contracts'

import { rmSync } from 'node:fs'
import { join } from 'node:path'

import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import { buildExperimentManifest, DEFAULT_REGISTRY_PATH, readRegistry, registerExperimentManifest, REGISTRY_SCHEMA } from './experiment'

const REG_PATH = join(process.cwd(), 'eval', '.experiment-test.registry.json')

const base = {
  id: 'test-exp',
  name: 'Test experiment',
  seed: 0,
  conditions: [{ name: 'on', description: 'gating on' }, { name: 'off', description: 'gating off' }],
  metrics: ['recall', 'f1'],
}

beforeAll(() => rmSync(REG_PATH, { force: true }))
afterAll(() => rmSync(REG_PATH, { force: true }))

describe('buildExperimentManifest', () => {
  it('builds a valid §38 manifest with pinned seed, conditions and metrics', () => {
    const m = buildExperimentManifest(base)
    expect(m.schema).toBe('aijade.experiment_manifest@1')
    expect(m.id).toBe('test-exp')
    expect(Number.isFinite(m.seed)).toBe(true)
    expect(m.conditions.length).toBe(2)
    expect(m.metrics.length).toBe(2)
    expect(m.version).toMatch(/^\d+\.\d+\.\d+/) // package.json version
    expect(m.createdAt).toBeGreaterThan(0)
  })

  it('defaults the seed to 0 and reads the package version when omitted', () => {
    const m = buildExperimentManifest({ ...base, seed: undefined })
    expect(m.seed).toBe(0)
    expect(typeof m.version).toBe('string')
  })

  it('attaches notes when provided', () => {
    const m = buildExperimentManifest({ ...base, notes: 'diagnostic only' })
    expect(m.notes).toBe('diagnostic only')
  })

  it('throws when conditions are empty (§38 requires ≥1)', () => {
    expect(() => buildExperimentManifest({ ...base, conditions: [] })).toThrow(/condition/i)
  })

  it('throws when metrics are empty (§38 requires ≥1 reported metric)', () => {
    expect(() => buildExperimentManifest({ ...base, metrics: [] })).toThrow(/metric/i)
  })

  it('throws on a non-finite seed', () => {
    expect(() => buildExperimentManifest({ ...base, seed: Number.NaN })).toThrow(/seed/i)
  })
})

describe('registerExperimentManifest / readRegistry', () => {
  it('upserts into the committed registry and persists it', () => {
    const m = buildExperimentManifest(base)
    const reg = registerExperimentManifest(m, REG_PATH)
    expect(reg.schema).toBe(REGISTRY_SCHEMA)
    expect(reg.count).toBe(1)
    expect(reg.experiments['test-exp']).toBeDefined()

    const reread = readRegistry(REG_PATH)
    expect(reread.count).toBe(1)
    expect(reread.experiments['test-exp'].id).toBe('test-exp')
  })

  it('re-registration of the same id overwrites but preserves createdAt (provenance)', () => {
    // 'test-exp' already exists from the prior test — capture its original stamp.
    const before = readRegistry(REG_PATH).experiments['test-exp'].createdAt
    const first = buildExperimentManifest(base)
    registerExperimentManifest(first, REG_PATH)
    // second registration a moment later — createdAt must be preserved, name updated
    const second = buildExperimentManifest({ ...base, name: 'Test experiment (updated)' })
    const reg = registerExperimentManifest(second, REG_PATH)
    expect(reg.count).toBe(1)
    expect(reg.experiments['test-exp'].name).toBe('Test experiment (updated)')
    expect(reg.experiments['test-exp'].createdAt).toBe(before)
    expect(reg.experiments['test-exp'].createdAt).not.toBe(second.createdAt)
  })

  it('accumulates distinct experiment ids', () => {
    const other = buildExperimentManifest({ ...base, id: 'test-exp-2', name: 'Second' })
    const reg = registerExperimentManifest(other, REG_PATH)
    expect(reg.count).toBe(2)
    expect(Object.keys(reg.experiments).sort()).toEqual(['test-exp', 'test-exp-2'])
  })

  it('refuses to register an invalid manifest', () => {
    const bad = { ...buildExperimentManifest(base) } as ExperimentManifest
    bad.conditions = []
    expect(() => registerExperimentManifest(bad, REG_PATH)).toThrow(/invalid/i)
  })

  it('readRegistry returns an empty registry when the file is absent', () => {
    const missing = readRegistry(join(process.cwd(), 'eval', '.does-not-exist.registry.json'))
    expect(missing.count).toBe(0)
    expect(missing.experiments).toEqual({})
  })
})

describe('default registry path', () => {
  it('lives outside results/ so it is version-controlled (not git-ignored)', () => {
    expect(DEFAULT_REGISTRY_PATH).not.toContain('results/')
    expect(DEFAULT_REGISTRY_PATH.startsWith('eval/')).toBe(true)
  })
})
