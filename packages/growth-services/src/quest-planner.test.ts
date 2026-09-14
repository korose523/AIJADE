import { validateLearningQuest } from '@proj-aijade/memory-biomimetic'
import { describe, expect, it } from 'vitest'

import { InMemoryStorage } from './in-memory'
import { QuestPlanner, questStatusToStage } from './quest-planner'
import { FixedScheduler } from './test-helpers'

function makeService() {
  return new QuestPlanner(
    { storage: new InMemoryStorage(), scheduler: new FixedScheduler(1_700_000_000_000) },
    'agent-1',
    'scope-1',
  )
}

describe('questPlanner', () => {
  it('creates a bounded quest that passes validateLearningQuest', async () => {
    const svc = makeService()
    const quest = await svc.createQuest({
      interestThreadRef: 'it-1',
      researchQuestion: 'how do birds migrate?',
      operationalDefinition: 'measure seasonal routes',
      expectedInformationGain: 0.6,
      questionType: 'academic',
      experimentManifestRef: 'exp-1',
    })
    expect(validateLearningQuest(quest).ok).toBe(true)
    expect(quest.status).toBe('active')
    expect(quest.sourcePlan.sourceTypes.length).toBeGreaterThan(0)
    expect(quest.stopConditions.length).toBeGreaterThan(0)
  })

  it('transitions a quest through the AEL state machine', async () => {
    const svc = makeService()
    const quest = await svc.createQuest({
      interestThreadRef: 'it-1',
      researchQuestion: 'q?',
      operationalDefinition: 'd',
      expectedInformationGain: 0.5,
      questionType: 'technical',
      experimentManifestRef: 'exp-1',
    })
    // terminal mapping: satisfied has no upstream stage
    expect(questStatusToStage('satisfied')).toBeNull()
    // fail from active → failed
    const failed = await svc.transition(quest.id, 'fail')
    expect(failed?.status).toBe('failed')
    // a failed (terminal) quest cannot transition further
    expect(await svc.transition(failed!.id, 'advance')).toBeNull()
  })

  it('marks a quest satisfied', async () => {
    const svc = makeService()
    const quest = await svc.createQuest({
      interestThreadRef: 'it-1',
      researchQuestion: 'q?',
      operationalDefinition: 'd',
      expectedInformationGain: 0.5,
      questionType: 'everyday',
      experimentManifestRef: 'exp-1',
    })
    const sat = await svc.satisfy(quest.id)
    expect(sat?.status).toBe('satisfied')
  })

  it('rejects an empty research question (boundary: §48.2)', async () => {
    const svc = makeService()
    await expect(
      svc.createQuest({
        interestThreadRef: 'it-1',
        researchQuestion: '',
        operationalDefinition: 'd',
        expectedInformationGain: 0.5,
        questionType: 'academic',
        experimentManifestRef: 'exp-1',
      }),
    ).rejects.toThrow(/LearningQuest rejected/)
  })
})
