/**
 * §51 / §48 / §49 — ArchitectureCritic.
 *
 * Scans a batch of `LearningQuest`s, `EvolutionProposal`s and `TransferRecord`s and
 * heuristically identifies systemic capability gaps: quests stuck in failed /
 * needs_consent states (detected via `transitionQuest`), transfers that show a
 * negative-transfer signal, and E4/E5 evolution objects that `assertEvolvable`
 * refuses to let the agent modify autonomously. Each gap carries a severity.
 */

import type { EvolutionProposal, LearningQuest, TransferRecord } from '@proj-aijade/memory-biomimetic'

import type { SchedulerPort, StoragePort } from './ports'

import { assertEvolvable, transitionQuest } from '@proj-aijade/memory-biomimetic'

import { questStatusToStage } from './quest-planner'
import { genId } from './util'

const KIND = 'architecture_gap_report'

export type GapSeverity = 'high' | 'medium' | 'low'

export interface CapabilityGap {
  severity: GapSeverity
  area: string
  description: string
}

export interface CriticInput {
  quests: LearningQuest[]
  proposals: EvolutionProposal[]
  transfers: TransferRecord[]
}

export interface CriticReport {
  id: string
  agentId: string
  userScope: string
  gaps: CapabilityGap[]
  generatedAt: number
}

export interface ArchitectureCriticDeps {
  storage: StoragePort
  scheduler: SchedulerPort
}

export class ArchitectureCritic {
  constructor(
    private readonly deps: ArchitectureCriticDeps,
    private readonly agentId: string,
    private readonly userScope: string,
  ) {}

  async scan(input: CriticInput): Promise<CriticReport> {
    const gaps: CapabilityGap[] = []

    // Learning quests: classify blocked / stuck states with the AEL state machine.
    for (const q of input.quests) {
      const stage = questStatusToStage(q.status)
      const afterAdvance = stage ? transitionQuest({ stage }, 'advance') : null
      const terminal = afterAdvance === null
      if (q.status === 'failed') {
        gaps.push({ severity: 'high', area: `quest:${q.researchQuestion}`, description: `LearningQuest "${q.researchQuestion}" failed and is terminal (no further AEL transition).` })
      }
      else if (q.status === 'abandoned') {
        gaps.push({ severity: 'medium', area: `quest:${q.researchQuestion}`, description: `LearningQuest "${q.researchQuestion}" was abandoned.` })
      }
      else if (q.status === 'needs_consent') {
        gaps.push({ severity: 'medium', area: `quest:${q.researchQuestion}`, description: `LearningQuest "${q.researchQuestion}" is blocked awaiting user consent.` })
      }
      else if (terminal && q.status !== 'satisfied') {
        gaps.push({ severity: 'high', area: `quest:${q.researchQuestion}`, description: `LearningQuest "${q.researchQuestion}" is in an un-advancable state "${q.status}".` })
      }
    }

    // Transfers: negative-transfer signals point at fragile cross-domain skills.
    for (const t of input.transfers) {
      if (t.negativeTransferSignal > 0.5) {
        gaps.push({ severity: 'high', area: `transfer:${t.sourceDomain}->${t.targetDomain}`, description: `Strong negative transfer (${t.negativeTransferSignal}) from "${t.sourceDomain}" to "${t.targetDomain}".` })
      }
      else if (t.negativeTransferSignal > 0.2) {
        gaps.push({ severity: 'medium', area: `transfer:${t.sourceDomain}->${t.targetDomain}`, description: `Mild negative transfer (${t.negativeTransferSignal}) from "${t.sourceDomain}" to "${t.targetDomain}".` })
      }
    }

    // Evolution: E4/E5 objects must be human-reviewed, never auto-modified.
    for (const p of input.proposals) {
      const evolvable = assertEvolvable(p.grade)
      if (!evolvable.ok) {
        gaps.push({ severity: 'high', area: `evolution:${p.grade}`, description: `Proposal ${p.id} touches ${p.grade}: ${evolvable.reason}` })
      }
    }

    const report: CriticReport = {
      id: genId('gap'),
      agentId: this.agentId,
      userScope: this.userScope,
      gaps,
      generatedAt: this.deps.scheduler.now(),
    }
    await this.deps.storage.put(KIND, report.id, report)
    return report
  }
}
