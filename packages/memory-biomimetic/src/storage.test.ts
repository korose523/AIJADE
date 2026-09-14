import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { DEFAULT_HAC_CONFIG } from './hac'
import { InMemoryStorageAdapter, JsonFileStorageAdapter } from './storage'
import { BioticMemory } from './store'
import { DEFAULT_MEMORY_CONFIG } from './types'

describe('v7 §26 storage tiering', () => {
  it('no adapter: store stays fully in-memory and never touches disk', () => {
    const mem = new BioticMemory(DEFAULT_MEMORY_CONFIG)
    expect(mem.episodes).toHaveLength(0)
    mem.encode({ id: 'e1', content: 'a deadline tomorrow', createdAt: 1, context: { tags: [] } })
    expect(mem.episodes).toHaveLength(1)
  })

  it('rehydrates identical state across two instances sharing one adapter', () => {
    const adapter = new InMemoryStorageAdapter()
    const m1 = new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, storage: adapter })
    m1.encode({ id: 'e1', content: 'deadline tomorrow', createdAt: 1, context: { tags: [] } })
    m1.encode({ id: 'e2', content: 'project kickoff', createdAt: 2, context: { tags: [] } })
    m1.proposeBelief({ proposition: 'user cares about deadlines', evidenceIds: ['e1', 'e2'] })

    // m2 is constructed later with the same adapter → must resume exactly where m1 left off.
    const m2 = new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, storage: adapter })
    expect(m2.episodes.map(e => e.id).sort()).toEqual(['e1', 'e2'])
    expect(m2.beliefs.map(b => b.proposition)).toEqual(['user cares about deadlines'])
    expect(m2.beliefRejections).toHaveLength(0)
  })

  it('records a sourceless belief as a rejection (§6) and rehydrates it too', () => {
    const adapter = new InMemoryStorageAdapter()
    const m1 = new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, storage: adapter })
    m1.proposeBelief({ proposition: 'unsourced claim', evidenceIds: [] })
    expect(m1.beliefRejections).toHaveLength(1)

    const m2 = new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, storage: adapter })
    expect(m2.beliefRejections).toHaveLength(1)
    expect(m2.beliefs).toHaveLength(0)
  })

  it('rehydrates HAC endogenous state when enabled (falsifiable durability)', () => {
    const adapter = new InMemoryStorageAdapter()
    const m1 = new BioticMemory({
      ...DEFAULT_MEMORY_CONFIG,
      hac: { ...DEFAULT_HAC_CONFIG, enabled: true },
      storage: adapter,
    })
    m1.stepHac(
      { a: 0.5, v: 0.5, d: 0.5, n: 0.5, s: 0.5, c: 0.5, b: 0.5 },
      { a: 0.6, v: 0.6, d: 0.6, n: 0.6, s: 0.6, c: 0.6, b: 0.6 },
    )
    const z1 = m1.hacState()!

    const m2 = new BioticMemory({
      ...DEFAULT_MEMORY_CONFIG,
      hac: { ...DEFAULT_HAC_CONFIG, enabled: true },
      storage: adapter,
    })
    expect(m2.hacState()).toEqual(z1)
    expect(m2.hacState()).not.toEqual({ a: 0.5, v: 0.5, d: 0.5, n: 0.5, s: 0.5, c: 0.5, b: 0.5 })
  })

  it('jsonFileStorageAdapter persists to disk and reloads', () => {
    const file = join(tmpdir(), `mem_snap_${Date.now()}_${Math.random().toString(36).slice(2)}.json`)
    const adapter = new JsonFileStorageAdapter(file)
    const m1 = new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, storage: adapter })
    m1.encode({ id: 'e1', content: 'persisted content', createdAt: 1, context: { tags: [] } })

    const m2 = new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, storage: adapter })
    expect(m2.episodes.map(e => e.id)).toEqual(['e1'])

    adapter.clear()
    const m3 = new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, storage: adapter })
    expect(m3.episodes).toHaveLength(0)
  })
})
