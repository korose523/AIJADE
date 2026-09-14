import type { EvolutionProposal, LearningQuest, TransferRecord } from '@proj-aijade/memory-biomimetic'

import { describe, expect, it } from 'vitest'

import { ArchitectureCritic } from './architecture-critic'
import { InMemoryStorage } from './in-memory'
import { FixedScheduler } from './test-helpers'

function makeService() {
  return new ArchitectureCritic(
    { storage: new InMemoryStorage(), scheduler: new FixedScheduler(1_700_000_000_000) },
    'agent-1',
    'scope-1',
  )
}

function quest(status: LearningQuest['status']): LearningQuest {
  return {
    id: 'q-1',
    schema: 'aijade.learning_quest@1',
    agentId: 'a',
    userScope: 's',
    interestThreadRef: 'it-1',
    researchQuestion: 'how?',
    operationalDefinition: 'measure',
    priorBeliefs: [],
    expectedInformationGain: 0.5,
    sourcePlan: { questionType: 'academic', sourceTypes: ['paper'], maxSources: 8 },
    resourceBudget: { allocated: 50, spent: 0, unit: 'queries' },
    privacyClass: 'public',
    stopConditions: ['budget reached'],
    successCriteria: ['answered'],
    deliverables: ['claim_map'],
    experimentManifestRef: 'exp-1',
    status,
    createdAt: 1,
  }
}

function proposal(grade: EvolutionProposal['grade']): EvolutionProposal {
  return {
    id: 'ep-1',
    schema: 'aijade.evolution_proposal@1',
    agentId: 'a',
    triggerEvidence: [],
    affectedComponents: ['x'],
    grade,
    baselineVersion: 'v1',
    changeSpec: 'change',
    sourceDiff: 'diff',
    generatedBy: 'agent',
    tests: [{ kind: 'contract_property', passed: true }],
    rollbackPlan: 'rollback',
    approvalPolicy: 'agent_self_review',
    signature: 'sig',
    createdAt: 1,
  }
}

function transfer(signal: number): TransferRecord {
  return {
    id: 'tr-1',
    schema: 'aijade.transfer_record@1',
    agentId: 'a',
    userScope: 's',
    sourceDomain: 'math',
    targetDomain: 'physics',
    invariantsPreserved: [],
    brokenConditions: [],
    predictedOutcome: 'p',
    measuredOutcome: 'p',
    negativeTransferSignal: signal,
    tier: 'T1',
    validated: false,
    createdAt: 1,
  }
}

describe('architectureCritic', () => {
  it('flags a failed quest as a high-severity gap (kernel transitionQuest used)', async () => {
    const svc = makeService()
    const report = await svc.scan({ quests: [quest('failed')], proposals: [], transfers: [] })
    const gap = report.gaps.find(g => g.area.includes('quest'))
    expect(gap?.severity).toBe('high')
  })

  it('flags a needs_consent quest as a medium gap', async () => {
    const svc = makeService()
    const report = await svc.scan({ quests: [quest('needs_consent')], proposals: [], transfers: [] })
    expect(report.gaps.some(g => g.severity === 'medium')).toBe(true)
  })

  it('flags strong negative transfer as high severity', async () => {
    const svc = makeService()
    const report = await svc.scan({ quests: [], proposals: [], transfers: [transfer(0.8)] })
    expect(report.gaps[0]?.severity).toBe('high')
  })

  it('flags E4 evolution proposals as non-evolvable high gaps (kernel assertEvolvable)', async () => {
    const svc = makeService()
    const report = await svc.scan({ quests: [], proposals: [proposal('E4')], transfers: [] })
    expect(report.gaps[0]?.severity).toBe('high')
  })

  it('produces an empty report for a healthy scan', async () => {
    const svc = makeService()
    const report = await svc.scan({ quests: [quest('active')], proposals: [proposal('E1')], transfers: [transfer(0.1)] })
    expect(report.gaps.length).toBe(0)
  })
})
