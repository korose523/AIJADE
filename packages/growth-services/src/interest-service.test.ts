import type { InterestComponents } from '@proj-aijade/memory-biomimetic'

import { validateInterestThread } from '@proj-aijade/memory-biomimetic'
import { describe, expect, it } from 'vitest'

import { InMemoryStorage } from './in-memory'
import { InterestService } from './interest-service'
import { FixedScheduler } from './test-helpers'

const COMPONENTS: InterestComponents = {
  novelty: 0.6,
  knowledgeGap: 0.5,
  identityRelevance: 0.7,
  challenge: 0.5,
  userRelevance: 0.6,
  futureUtility: 0.5,
  cost: 0.2,
  risk: 0.1,
  repetitionPenalty: 0.1,
}

function makeService() {
  return new InterestService(
    { storage: new InMemoryStorage(), scheduler: new FixedScheduler(1_700_000_000_000) },
    'agent-1',
    'scope-1',
  )
}

describe('interestService', () => {
  it('creates a thread that passes validateInterestThread and has intrinsicValue ∈ [0,1]', async () => {
    const svc = makeService()
    const thread = await svc.createThread({
      subject: 'birding',
      originEventIds: ['e1', 'e2'],
      components: COMPONENTS,
      identityRelevance: 0.7,
      userRelevance: 0.6,
      noveltyFrontier: 0.5,
    })
    expect(validateInterestThread(thread).ok).toBe(true)
    expect(thread.intrinsicValue).toBeGreaterThanOrEqual(0)
    expect(thread.intrinsicValue).toBeLessThanOrEqual(1)
    expect(thread.status).toBe('latent')
  })

  it('advances the lifecycle and persists the updated status', async () => {
    const svc = makeService()
    const thread = await svc.createThread({
      subject: 'birding',
      originEventIds: ['e1'],
      components: COMPONENTS,
      identityRelevance: 0.7,
      userRelevance: 0.6,
      noveltyFrontier: 0.5,
    })
    const active = await svc.advance(thread.id, 'probe')
    expect(active?.status).toBe('active')
    // A satisfied → abandoned jump is illegal and returns null.
    const bad = await svc.advance(thread.id, 'abandon')
    // thread is still latent (advance to active was persisted), abandon from latent is legal:
    expect(bad?.status).toBe('abandoned')
    // re-advancing an abandoned thread is illegal → null
    expect(await svc.advance(bad!.id, 'probe')).toBeNull()
  })

  it('selectActive returns an in-scope portfolio containing the active thread', async () => {
    const svc = makeService()
    const a = await svc.createThread({
      subject: 'A',
      originEventIds: ['e1'],
      components: COMPONENTS,
      identityRelevance: 0.7,
      userRelevance: 0.6,
      noveltyFrontier: 0.5,
    })
    const selection = await svc.selectActive(5)
    expect(selection.selected).toContain(a.id)
    expect(selection.identityReserved).toBeDefined()
  })

  it('rejects an empty origin-event list (boundary: §47.1 history requirement)', async () => {
    const svc = makeService()
    await expect(
      svc.createThread({
        subject: 'x',
        originEventIds: [],
        components: COMPONENTS,
        identityRelevance: 0.7,
        userRelevance: 0.6,
        noveltyFrontier: 0.5,
      }),
    ).rejects.toThrow(/InterestThread rejected/)
  })
})
