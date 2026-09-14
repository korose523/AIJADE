/**
 * §50.3 — LifeJournal.
 *
 * Aggregates a day's interests, quests, claims, beliefs, skills, open questions
 * and identity reflections into a privacy-filtered `LifeJournalEntry`. The entry
 * carries an ISO date, a `sharePolicy` and evidence references, and is validated.
 */

import type { LifeJournalEntry } from '@proj-aijade/memory-biomimetic'

import type { SchedulerPort, StoragePort } from './ports'

import { validateLifeJournalEntry } from '@proj-aijade/memory-biomimetic'

import { genId, todayISO } from './util'

const KIND = 'life_journal_entry'

export interface ComposeInput {
  /** ISO date; defaults to today in local time. */
  date?: string
  experiencedEvents?: string[]
  activeInterests?: string[]
  learnedClaims?: string[]
  changedBeliefs?: string[]
  practicedSkills?: string[]
  unresolvedQuestions?: string[]
  identityReflections?: string[]
  sharePolicy?: 'private' | 'diary_only' | 'shareable'
  evidenceRefs?: string[]
}

export interface LifeJournalDeps {
  storage: StoragePort
  scheduler: SchedulerPort
}

export class LifeJournal {
  constructor(
    private readonly deps: LifeJournalDeps,
    private readonly agentId: string,
    private readonly userScope: string,
  ) {}

  async compose(input: ComposeInput): Promise<LifeJournalEntry> {
    const entry: LifeJournalEntry = {
      id: genId('lj'),
      schema: 'aijade.life_journal_entry@1',
      agentId: this.agentId,
      userScope: this.userScope,
      date: input.date ?? todayISO(this.deps.scheduler.now()),
      experiencedEvents: input.experiencedEvents ?? [],
      activeInterests: input.activeInterests ?? [],
      learnedClaims: input.learnedClaims ?? [],
      changedBeliefs: input.changedBeliefs ?? [],
      practicedSkills: input.practicedSkills ?? [],
      unresolvedQuestions: input.unresolvedQuestions ?? [],
      identityReflections: input.identityReflections ?? [],
      sharePolicy: input.sharePolicy ?? 'private',
      evidenceRefs: input.evidenceRefs ?? [],
      createdAt: this.deps.scheduler.now(),
    }
    const check = validateLifeJournalEntry(entry)
    if (!check.ok)
      throw new Error(`LifeJournalEntry rejected: ${check.reason}`)
    await this.deps.storage.put(KIND, entry.id, entry)
    return entry
  }

  async get(id: string): Promise<LifeJournalEntry | undefined> {
    return this.deps.storage.get<LifeJournalEntry>(KIND, id)
  }
}
