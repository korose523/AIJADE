import type { InterestComponents } from '@proj-aijade/memory-biomimetic'

import type { RawHit } from './ports'

import { describe, expect, it } from 'vitest'

import { makeGrowthLoop } from './growth-loop'
import { defaultPorts } from './in-memory'

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

const SEED: RawHit[] = [
  { locator: 'https://example.com/birds', sourceType: 'web', content: 'birds migrate south in winter', fetchedAt: 1_700_000_000_000 },
]

describe('growthLoop (integration)', () => {
  it('runs one full developmental cycle without throwing and produces a summary', async () => {
    const loop = makeGrowthLoop(defaultPorts({ searchSeed: SEED }), 'agent-1', 'scope-1')
    const summary = await loop.runOnce({
      subject: 'bird migration',
      originEventIds: ['e1'],
      components: COMPONENTS,
      identityRelevance: 0.7,
      userRelevance: 0.6,
      noveltyFrontier: 0.5,
      researchQuestion: 'how do birds migrate?',
      operationalDefinition: 'trace seasonal routes',
      expectedInformationGain: 0.6,
      questionType: 'academic',
      query: 'birds',
      sourceTypes: ['web'],
    })
    expect(summary.skipped).toBe(false)
    expect(summary.interestThreadId).toBeDefined()
    expect(summary.questId).toBeDefined()
    expect(summary.sourceCount).toBeGreaterThan(0)
    expect(summary.claimMapId).toBeDefined()
    expect(summary.artifactId).toBeDefined()
    expect(summary.journalId).toBeDefined()
    expect(summary.shareCandidateId).toBeDefined()
    expect(typeof summary.shareScore).toBe('number')
  })

  it('skips the cycle when the growth_loop budget is exhausted (boundary)', async () => {
    const loop = makeGrowthLoop(
      defaultPorts({ searchSeed: SEED, budgets: { growth_loop: 0 } }),
      'agent-1',
      'scope-1',
    )
    const summary = await loop.runOnce({
      subject: 'x',
      originEventIds: ['e1'],
      components: COMPONENTS,
      identityRelevance: 0.7,
      userRelevance: 0.6,
      noveltyFrontier: 0.5,
      researchQuestion: 'q?',
      operationalDefinition: 'd',
      expectedInformationGain: 0.5,
      questionType: 'academic',
      query: 'birds',
    })
    expect(summary.skipped).toBe(true)
    expect(summary.reason).toMatch(/budget exhausted/)
  })
})
