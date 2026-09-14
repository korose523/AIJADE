import { validateLifeJournalEntry } from '@proj-aijade/memory-biomimetic'
import { describe, expect, it } from 'vitest'

import { InMemoryStorage } from './in-memory'
import { LifeJournal } from './life-journal'
import { FixedScheduler } from './test-helpers'

function makeService() {
  return new LifeJournal(
    { storage: new InMemoryStorage(), scheduler: new FixedScheduler(1_700_000_000_000) },
    'agent-1',
    'scope-1',
  )
}

describe('lifeJournal', () => {
  it('composes a privacy-filtered entry that passes validateLifeJournalEntry', async () => {
    const svc = makeService()
    const entry = await svc.compose({
      activeInterests: ['it-1'],
      learnedClaims: ['cm-1'],
      sharePolicy: 'shareable',
    })
    expect(validateLifeJournalEntry(entry).ok).toBe(true)
    expect(entry.date).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(entry.sharePolicy).toBe('shareable')
  })

  it('rejects a malformed date (boundary: ISO YYYY-MM-DD)', async () => {
    const svc = makeService()
    await expect(svc.compose({ date: 'not-a-date' })).rejects.toThrow(/LifeJournalEntry rejected/)
  })
})
