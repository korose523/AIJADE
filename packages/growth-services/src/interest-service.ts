/**
 * §47 DIVE — InterestService.
 *
 * Turns developmental interest components into a persisted `InterestThread`
 * (computing intrinsic value, identity/user relevance, novelty frontier and
 * progress), advances the thread through its lifecycle with `nextInterestStatus`,
 * and selects a daily attention-budget portfolio with `selectPortfolio`.
 */

import type {
  InterestComponents,
  InterestSignal,
  InterestThread,
  PortfolioCandidate,
  PortfolioOptions,
  PortfolioSelection,
} from '@proj-aijade/memory-biomimetic'

import type { SchedulerPort, StoragePort } from './ports'

import {
  DEFAULT_INTEREST_WEIGHTS,
  intrinsicValue,
  nextInterestStatus,
  selectPortfolio,
  validateInterestThread,
} from '@proj-aijade/memory-biomimetic'

import { genId } from './util'

const KIND = 'interest_thread'

export interface CreateThreadInput {
  subject: string
  originEventIds: string[]
  components: InterestComponents
  identityRelevance: number
  userRelevance: number
  noveltyFrontier: number
  motivatingQuestions?: string[]
  knowledgeGaps?: string[]
  currentHypotheses?: string[]
  progress?: number
  attentionBudget?: { allocated: number, spent: number, unit: 'minutes' | 'queries' | 'tokens' }
}

export interface InterestServiceDeps {
  storage: StoragePort
  scheduler: SchedulerPort
}

export class InterestService {
  constructor(
    private readonly deps: InterestServiceDeps,
    private readonly agentId: string,
    private readonly userScope: string,
  ) {}

  /** Create and persist a new latent interest thread from its components. */
  async createThread(input: CreateThreadInput): Promise<InterestThread> {
    const now = this.deps.scheduler.now()
    const v = intrinsicValue(input.components, DEFAULT_INTEREST_WEIGHTS)
    const thread: InterestThread = {
      id: genId('it'),
      schema: 'aijade.interest_thread@1',
      agentId: this.agentId,
      userScope: this.userScope,
      subject: input.subject,
      originEventIds: input.originEventIds,
      motivatingQuestions: input.motivatingQuestions ?? [],
      intrinsicValue: v,
      identityRelevance: input.identityRelevance,
      userRelevance: input.userRelevance,
      noveltyFrontier: input.noveltyFrontier,
      knowledgeGaps: input.knowledgeGaps ?? [],
      currentHypotheses: input.currentHypotheses ?? [],
      progress: input.progress ?? 0,
      attentionBudget: input.attentionBudget ?? { allocated: 60, spent: 0, unit: 'minutes' },
      status: 'latent',
      lastReflectedAt: now,
    }
    const check = validateInterestThread(thread)
    if (!check.ok)
      throw new Error(`InterestThread rejected: ${check.reason}`)
    // A freshly seeded thread is latent (seed → latent).
    void nextInterestStatus('latent', 'seed')
    await this.deps.storage.put(KIND, thread.id, thread)
    return thread
  }

  /** Advance a thread's lifecycle status. Returns the updated thread or null on an illegal transition. */
  async advance(id: string, signal: InterestSignal): Promise<InterestThread | null> {
    const thread = await this.deps.storage.get<InterestThread>(KIND, id)
    if (!thread)
      return null
    const next = nextInterestStatus(thread.status, signal)
    if (next === null)
      return null
    const updated: InterestThread = {
      ...thread,
      status: next,
      lastReflectedAt: this.deps.scheduler.now(),
      abandonedReason: next === 'abandoned' ? (thread.abandonedReason ?? 'advanced to abandoned') : thread.abandonedReason,
    }
    const check = validateInterestThread(updated)
    if (!check.ok)
      throw new Error(`InterestThread rejected: ${check.reason}`)
    await this.deps.storage.put(KIND, updated.id, updated)
    return updated
  }

  /** Select the active portfolio for this scope under a daily attention budget. */
  async selectActive(budget: number, options?: Omit<PortfolioOptions, 'budget'>): Promise<PortfolioSelection> {
    const threads = await this.deps.storage.query<InterestThread>(
      KIND,
      t => t.userScope === this.userScope && t.status !== 'abandoned',
    )
    const candidates: PortfolioCandidate[] = threads.map(t => ({
      thread: {
        id: t.id,
        subject: t.subject,
        intrinsicValue: t.intrinsicValue,
        identityRelevance: t.identityRelevance,
        userRelevance: t.userRelevance,
      },
    }))
    return selectPortfolio(candidates, { budget, ...options })
  }

  /** Load a single thread. */
  async get(id: string): Promise<InterestThread | undefined> {
    return this.deps.storage.get<InterestThread>(KIND, id)
  }

  /** List all threads for this scope. */
  async list(): Promise<InterestThread[]> {
    return this.deps.storage.query<InterestThread>(KIND, t => t.userScope === this.userScope)
  }
}
