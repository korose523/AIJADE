/**
 * §48 AEL — QuestPlanner.
 *
 * Creates bounded `LearningQuest` records (pinning an interest thread, a research
 * question, an operational definition, an expected information gain, a source plan
 * derived from `planSources`, a resource budget, privacy class, mandatory stop
 * conditions, success criteria, deliverables and an ExperimentManifest reference),
 * then advances them through their lifecycle with `transitionQuest`.
 */

import type { LearningQuest, QuestEvent, QuestionType, QuestStage } from '@proj-aijade/memory-biomimetic'

import type { SchedulerPort, StoragePort } from './ports'

import {
  planSources,
  transitionQuest,
  validateLearningQuest,
} from '@proj-aijade/memory-biomimetic'

import { genId } from './util'

const KIND = 'learning_quest'

export interface CreateQuestInput {
  interestThreadRef: string
  researchQuestion: string
  operationalDefinition: string
  expectedInformationGain: number
  questionType: QuestionType
  priorBeliefs?: string[]
  resourceBudget?: { allocated: number, spent: number, unit: 'queries' | 'minutes' | 'usd' | 'tokens' }
  privacyClass?: 'public' | 'private' | 'confidential'
  stopConditions?: string[]
  successCriteria?: string[]
  deliverables?: string[]
  experimentManifestRef: string
}

export interface QuestPlannerDeps {
  storage: StoragePort
  scheduler: SchedulerPort
}

/** Map a fine-grained AEL pipeline/exceptional stage onto the coarse quest status. */
function toQuestStatus(stage: QuestStage): LearningQuest['status'] {
  switch (stage) {
    case 'PAUSED':
      return 'paused'
    case 'NEEDS_USER_CONSENT':
      return 'needs_consent'
    case 'CONTRADICTED':
      return 'contradicted'
    case 'FAILED':
      return 'failed'
    case 'ABANDONED':
      return 'abandoned'
    default:
      // Any pipeline stage simply means "actively in progress".
      return 'active'
  }
}

/**
 * Reverse map: the coarse `LearningQuest.status` (human-readable, lower-case) back
 * onto the fine-grained `QuestStage` the AEL state machine operates on. `satisfied`
 * is terminal and has no upstream stage, so it maps to null (no further transition).
 */
export function questStatusToStage(status: LearningQuest['status']): QuestStage | null {
  switch (status) {
    case 'active':
      return 'OBSERVE'
    case 'paused':
      return 'PAUSED'
    case 'needs_consent':
      return 'NEEDS_USER_CONSENT'
    case 'contradicted':
      return 'CONTRADICTED'
    case 'failed':
      return 'FAILED'
    case 'abandoned':
      return 'ABANDONED'
    case 'satisfied':
      return null
  }
}

export class QuestPlanner {
  constructor(
    private readonly deps: QuestPlannerDeps,
    private readonly agentId: string,
    private readonly userScope: string,
  ) {}

  /** Create and persist a bounded learning quest. */
  async createQuest(input: CreateQuestInput): Promise<LearningQuest> {
    const now = this.deps.scheduler.now()
    const plan = planSources(input.questionType)
    const quest: LearningQuest = {
      id: genId('q'),
      schema: 'aijade.learning_quest@1',
      agentId: this.agentId,
      userScope: this.userScope,
      interestThreadRef: input.interestThreadRef,
      researchQuestion: input.researchQuestion,
      operationalDefinition: input.operationalDefinition,
      priorBeliefs: input.priorBeliefs ?? [],
      expectedInformationGain: input.expectedInformationGain,
      sourcePlan: { questionType: plan.questionType, sourceTypes: plan.sourceTypes, maxSources: 8 },
      resourceBudget: input.resourceBudget ?? { allocated: 50, spent: 0, unit: 'queries' },
      privacyClass: input.privacyClass ?? 'public',
      stopConditions: input.stopConditions ?? ['marginal information gain below 0.02', 'resource budget reached'],
      successCriteria: input.successCriteria ?? ['every motivating question answered', '≥1 claim with support'],
      deliverables: input.deliverables ?? ['claim_map', 'knowledge_artifact'],
      experimentManifestRef: input.experimentManifestRef,
      status: 'active',
      createdAt: now,
    }
    const check = validateLearningQuest(quest)
    if (!check.ok)
      throw new Error(`LearningQuest rejected: ${check.reason}`)
    await this.deps.storage.put(KIND, quest.id, quest)
    return quest
  }

  /** Advance a quest through its lifecycle. Returns the updated quest or null on an illegal transition. */
  async transition(id: string, event: QuestEvent): Promise<LearningQuest | null> {
    const quest = await this.deps.storage.get<LearningQuest>(KIND, id)
    if (!quest)
      return null
    const stage = questStatusToStage(quest.status)
    if (stage === null)
      return null
    const result = transitionQuest({ stage }, event)
    if (result === null)
      return null
    const updated: LearningQuest = { ...quest, status: toQuestStatus(result.stage) }
    const check = validateLearningQuest(updated)
    if (!check.ok)
      throw new Error(`LearningQuest rejected: ${check.reason}`)
    await this.deps.storage.put(KIND, updated.id, updated)
    return updated
  }

  /** Mark a quest satisfied (the REFLECT → advance completion state). */
  async satisfy(id: string): Promise<LearningQuest | null> {
    const quest = await this.deps.storage.get<LearningQuest>(KIND, id)
    if (!quest)
      return null
    const updated: LearningQuest = { ...quest, status: 'satisfied' }
    await this.deps.storage.put(KIND, updated.id, updated)
    return updated
  }

  async get(id: string): Promise<LearningQuest | undefined> {
    return this.deps.storage.get<LearningQuest>(KIND, id)
  }
}
