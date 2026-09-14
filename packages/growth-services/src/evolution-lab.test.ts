import { validateEvolutionProposal } from '@proj-aijade/memory-biomimetic'
import { describe, expect, it } from 'vitest'

import { EvolutionLab, makeCandidate } from './evolution-lab'
import { InMemorySigning, InMemoryStorage } from './in-memory'
import { FixedScheduler } from './test-helpers'

function makeService() {
  return new EvolutionLab(
    {
      storage: new InMemoryStorage(),
      scheduler: new FixedScheduler(1_700_000_000_000),
      signing: new InMemorySigning(),
    },
    'agent-1',
    'scope-1',
  )
}

const baseInput = {
  candidates: [makeCandidate({ id: 'c1' })],
  grade: 'E2' as const,
  baselineVersion: 'v1',
  changeSpec: 'improve caching',
  sourceDiff: '---a+++b',
  generatedBy: 'agent',
  rollbackPlan: 'git revert',
}

describe('evolutionLab', () => {
  it('emits a signed EvolutionProposal that passes validateEvolutionProposal', async () => {
    const svc = makeService()
    const { proposal } = await svc.evaluate(baseInput)
    expect(validateEvolutionProposal(proposal).ok).toBe(true)
    expect(proposal.signature.length).toBeGreaterThan(0)
  })

  it('refuses E4/E5 objects for autonomous modification (kernel assertEvolvable)', async () => {
    const svc = makeService()
    await expect(svc.evaluate({ ...baseInput, grade: 'E4' })).rejects.toThrow(/refused/)
  })

  it('throws when no candidate satisfies the evolution constraints (boundary)', async () => {
    const svc = makeService()
    await expect(
      svc.evaluate({ ...baseInput, candidates: [makeCandidate({ id: 'bad', safety: 0.5 })] }),
    ).rejects.toThrow(/no feasible candidate/)
  })

  it('exposes the best candidate and its objective', async () => {
    const svc = makeService()
    const res = await svc.evaluate(baseInput)
    expect(res.bestCandidate.id).toBe('c1')
    expect(typeof res.objective).toBe('number')
  })

  it('rejects a zero-length signature (boundary: signing failure)', async () => {
    // A signing port that returns an empty signature makes the proposal invalid.
    const broken = new EvolutionLab(
      {
        storage: new InMemoryStorage(),
        scheduler: new FixedScheduler(1_700_000_000_000),
        signing: { sign: () => '', verify: () => false },
      },
      'agent-1',
      'scope-1',
    )
    await expect(broken.evaluate(baseInput)).rejects.toThrow(/EvolutionProposal rejected/)
  })
})
