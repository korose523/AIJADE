/**
 * §46 — GrowthLoop orchestrator.
 *
 * Wires the growth services into one autonomous developmental cycle:
 *
 *   InterestService → QuestPlanner → KnowledgeAcquirer → EpistemicVerifier
 *   → SynthesisWorkbench → LifeJournal → SharingPolicy
 *
 * The whole cycle is guarded by a budget draw on the `SchedulerPort`, so a scope
 * that has exhausted its quota returns a skipped summary instead of running.
 */

import type { InterestComponents } from '@proj-aijade/memory-biomimetic'

import type { GrowthPorts, LlmPort, SchedulerPort, SearchPort, SigningPort, StoragePort } from './ports'

import { EpistemicVerifier } from './epistemic-verifier'
import { InterestService } from './interest-service'
import { KnowledgeAcquirer } from './knowledge-acquirer'
import { LifeJournal } from './life-journal'
import { QuestPlanner } from './quest-planner'
import { SharingPolicy } from './sharing-policy'
import { SynthesisWorkbench } from './synthesis-workbench'
import { genId } from './util'

export interface RunOnceInput {
  subject: string
  originEventIds: string[]
  components: InterestComponents
  identityRelevance: number
  userRelevance: number
  noveltyFrontier: number
  researchQuestion: string
  operationalDefinition: string
  expectedInformationGain: number
  questionType: 'timely_fact' | 'academic' | 'technical' | 'everyday' | 'subjective_culture'
  query: string
  sourceTypes?: string[]
  /** Optional override of the share utility; defaults to a moderate profile. */
  shareUtility?: {
    relevance: number
    novelty: number
    relationalValue: number
    timeliness: number
    uncertainty: number
    interruption: number
    privacyRisk: number
    repetition: number
  }
}

export interface GrowthLoopSummary {
  skipped: boolean
  reason?: string
  interestThreadId?: string
  questId?: string
  sourceCount: number
  claimMapId?: string
  artifactId?: string
  journalId?: string
  shareCandidateId?: string
  shareScore?: number
  shareChannel?: string
}

export interface GrowthLoopDeps {
  storage: StoragePort
  search: SearchPort
  signing: SigningPort
  scheduler: SchedulerPort
  /** Optional real LLM; when present, KnowledgeAcquirer emits an LLM brief. */
  llm?: LlmPort
}

export class GrowthLoop {
  private readonly interest: InterestService
  private readonly planner: QuestPlanner
  private readonly acquirer: KnowledgeAcquirer
  private readonly verifier: EpistemicVerifier
  private readonly synthesis: SynthesisWorkbench
  private readonly journal: LifeJournal
  private readonly sharing: SharingPolicy

  constructor(
    private readonly deps: GrowthLoopDeps,
    agentId: string,
    userScope: string,
  ) {
    this.interest = new InterestService({ storage: deps.storage, scheduler: deps.scheduler }, agentId, userScope)
    this.planner = new QuestPlanner({ storage: deps.storage, scheduler: deps.scheduler }, agentId, userScope)
    this.acquirer = new KnowledgeAcquirer({ storage: deps.storage, search: deps.search, scheduler: deps.scheduler, llm: deps.llm }, agentId, userScope)
    this.verifier = new EpistemicVerifier({ storage: deps.storage, scheduler: deps.scheduler }, agentId, userScope)
    this.synthesis = new SynthesisWorkbench({ storage: deps.storage, scheduler: deps.scheduler }, agentId, userScope)
    this.journal = new LifeJournal({ storage: deps.storage, scheduler: deps.scheduler }, agentId, userScope)
    this.sharing = new SharingPolicy({ storage: deps.storage, scheduler: deps.scheduler }, agentId, userScope)
  }

  async runOnce(input: RunOnceInput): Promise<GrowthLoopSummary> {
    // Budget gate: one unit per cycle; a quota-exhausted scope is skipped.
    if (!this.deps.scheduler.consumeBudget('growth_loop', 1)) {
      return { skipped: true, reason: 'growth_loop budget exhausted', sourceCount: 0 }
    }

    const thread = await this.interest.createThread({
      subject: input.subject,
      originEventIds: input.originEventIds,
      components: input.components,
      identityRelevance: input.identityRelevance,
      userRelevance: input.userRelevance,
      noveltyFrontier: input.noveltyFrontier,
    })

    const quest = await this.planner.createQuest({
      interestThreadRef: thread.id,
      researchQuestion: input.researchQuestion,
      operationalDefinition: input.operationalDefinition,
      expectedInformationGain: input.expectedInformationGain,
      questionType: input.questionType,
      experimentManifestRef: genId('exp'),
    })

    const sources = await this.acquirer.acquire({
      query: input.query,
      sourceTypes: input.sourceTypes,
      // Fire the real-LLM distillation step whenever an LLM port is injected.
      useLlmBrief: this.deps.llm != null,
    })

    let claimMapId: string | undefined
    let artifactId: string | undefined
    let beliefId: string | undefined
    if (sources.length > 0) {
      const verified = await this.verifier.verify({
        sources,
        questRef: quest.id,
        proposition: input.researchQuestion,
      })
      claimMapId = verified.claimMap.id
      beliefId = verified.belief.id

      const artifact = await this.synthesis.synthesize({
        questRef: quest.id,
        kind: 'learning_note',
        payload: { summary: input.researchQuestion, confidence: verified.confidence },
        sourceRecords: sources,
      })
      artifactId = artifact.id
    }

    const journal = await this.journal.compose({
      activeInterests: [thread.id],
      learnedClaims: claimMapId ? [claimMapId] : [],
      changedBeliefs: beliefId ? [beliefId] : [],
      sharePolicy: 'shareable',
      evidenceRefs: (claimMapId ? [claimMapId] : []).concat(artifactId ? [artifactId] : []),
    })

    const shareUtility = input.shareUtility ?? {
      relevance: 0.6,
      novelty: 0.5,
      relationalValue: 0.5,
      timeliness: 0.5,
      uncertainty: 0.3,
      interruption: 0.1,
      privacyRisk: 0.1,
      repetition: 0.1,
    }
    const share = await this.sharing.scoreShare({
      contentRef: artifactId ?? thread.id,
      utility: shareUtility,
    })

    return {
      skipped: false,
      interestThreadId: thread.id,
      questId: quest.id,
      sourceCount: sources.length,
      claimMapId,
      artifactId,
      journalId: journal.id,
      shareCandidateId: share.candidate.id,
      shareScore: share.candidate.score,
      shareChannel: share.candidate.channel,
    }
  }
}

/** Convenience: build a GrowthLoop from the bundled ports. */
export function makeGrowthLoop(ports: GrowthPorts, agentId: string, userScope: string): GrowthLoop {
  return new GrowthLoop(
    {
      storage: ports.storage,
      search: ports.search,
      signing: ports.signing,
      scheduler: ports.scheduler,
      llm: ports.llm,
    },
    agentId,
    userScope,
  )
}
