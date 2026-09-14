import type { RawHit } from './ports'

import { validateSourceRecord } from '@proj-aijade/memory-biomimetic'
import { describe, expect, it } from 'vitest'

import { InMemorySearch, InMemoryStorage } from './in-memory'
import { KnowledgeAcquirer } from './knowledge-acquirer'
import { FixedScheduler } from './test-helpers'

function seed(): RawHit[] {
  return [
    { locator: 'https://a.com/1', sourceType: 'web', content: 'birds migrate south in winter', fetchedAt: 1_700_000_000_000 },
    { locator: 'https://b.com/2', sourceType: 'paper', content: 'seasonal bird routes paper', fetchedAt: 1_700_000_000_001 },
  ]
}

function makeService(hits: RawHit[]) {
  return new KnowledgeAcquirer(
    { storage: new InMemoryStorage(), search: new InMemorySearch(hits), scheduler: new FixedScheduler(1_700_000_000_000) },
    'agent-1',
    'scope-1',
  )
}

describe('knowledgeAcquirer', () => {
  it('quarantines search hits into SourceRecords that pass validateSourceRecord', async () => {
    const svc = makeService(seed())
    const records = await svc.acquire({ query: 'bird', sourceTypes: ['web', 'paper'] })
    expect(records.length).toBe(2)
    for (const r of records) {
      expect(validateSourceRecord(r).ok).toBe(true)
      expect(r.contentHash.length).toBeGreaterThan(0)
    }
  })

  it('respects the maxSources cap', async () => {
    const svc = makeService(seed())
    const records = await svc.acquire({ query: 'bird', maxSources: 1 })
    expect(records.length).toBe(1)
  })

  it('returns an empty list when the search yields nothing (boundary)', async () => {
    const svc = makeService([])
    const records = await svc.acquire({ query: 'nothing' })
    expect(records).toEqual([])
  })

  it('marks trusted source types with a license tag', async () => {
    const svc = makeService([{ locator: 'https://official/1', sourceType: 'official_doc', content: 'trust me', fetchedAt: 1 }])
    const records = await svc.acquire({ query: 'trust', trustedTypes: ['official_doc'] })
    expect(records[0]?.license).toBe('trusted')
  })
})
