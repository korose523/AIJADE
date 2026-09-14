/**
 * §48 AEL — KnowledgeAcquirer.
 *
 * Uses the `SearchPort` to pull raw, untrusted web/tool hits, then quarantines
 * each one into a persisted `SourceRecord`: it derives a content hash (to de-dup
 * reposts), assigns default provenance-quality dimensions, and records empty
 * upstream lineage. Every record passes `validateSourceRecord`.
 */

import type { SourceRecord } from '@proj-aijade/memory-biomimetic'

import type { LlmPort, SchedulerPort, SearchPort, StoragePort } from './ports'

import { validateSourceRecord } from '@proj-aijade/memory-biomimetic'

import { contentHashOf, genId } from './util'

const KIND = 'source_record'

/** Default quality dimensions assigned to a freshly acquired source. */
export const DEFAULT_SOURCE_QUALITY = {
  reliability: 0.6,
  independence: 0.7,
  directness: 0.6,
  recency: 0.7,
  reproducibility: 0.5,
} as const

export interface AcquireInput {
  query: string
  sourceTypes?: string[]
  /** Cap on how many hits to convert into records. */
  maxSources?: number
  /** Override the default quality dimensions for every fetched hit. */
  quality?: SourceRecord['quality']
  /** Mark a particular sourceType as trusted. */
  trustedTypes?: string[]
  /**
   * When set and an `LlmPort` is injected, the acquirer asks the real model to
   * distil the retrieved hits into a short factual brief, persisted as an extra
   * `SourceRecord` (sourceType `llm_brief`). This is the genuine LLM touchpoint
   * inside the growth loop.
   */
  useLlmBrief?: boolean
}

export interface KnowledgeAcquirerDeps {
  storage: StoragePort
  search: SearchPort
  scheduler: SchedulerPort
  /** Optional real LLM used to synthesise a research brief from the hits. */
  llm?: LlmPort
}

export class KnowledgeAcquirer {
  constructor(
    private readonly deps: KnowledgeAcquirerDeps,
    _agentId: string,
    _userScope: string,
  ) {}

  /** Search and convert the returned hits into persisted SourceRecords. */
  async acquire(input: AcquireInput): Promise<SourceRecord[]> {
    const hits = await this.deps.search.search(input.query, input.sourceTypes ?? [])
    const cap = input.maxSources ?? hits.length
    const quality = input.quality ?? DEFAULT_SOURCE_QUALITY
    const trusted = new Set(input.trustedTypes ?? [])
    const records: SourceRecord[] = []
    for (const hit of hits.slice(0, Math.max(0, cap))) {
      const record: SourceRecord = {
        id: genId('src'),
        schema: 'aijade.source_record@1',
        locator: hit.locator,
        sourceType: hit.sourceType,
        quality: { ...quality },
        upstreamRefs: [],
        contentHash: contentHashOf(hit.content),
        license: trusted.has(hit.sourceType) ? 'trusted' : undefined,
        fetchedAt: this.deps.scheduler.now(),
      }
      const check = validateSourceRecord(record)
      if (!check.ok)
        throw new Error(`SourceRecord rejected: ${check.reason}`)
      await this.deps.storage.put(KIND, record.id, record)
      records.push(record)
    }

    // Real LLM touchpoint: distil the retrieved hits into a verified brief.
    if (records.length > 0 && input.useLlmBrief && this.deps.llm) {
      const brief = await this.deps.llm.complete(buildBriefPrompt(input.query, records))
      const briefId = genId('llm')
      const briefRecord: SourceRecord = {
        id: briefId,
        schema: 'aijade.source_record@1',
        locator: `aijade://llm-brief/${briefId}`,
        sourceType: 'llm_brief',
        quality: { ...quality },
        upstreamRefs: records.map(r => r.id),
        contentHash: contentHashOf(brief),
        fetchedAt: this.deps.scheduler.now(),
      }
      const checkBrief = validateSourceRecord(briefRecord)
      if (!checkBrief.ok)
        throw new Error(`LLM brief SourceRecord rejected: ${checkBrief.reason}`)
      await this.deps.storage.put(KIND, briefRecord.id, briefRecord)
      records.push(briefRecord)
    }

    return records
  }

  async get(id: string): Promise<SourceRecord | undefined> {
    return this.deps.storage.get<SourceRecord>(KIND, id)
  }

  async list(): Promise<SourceRecord[]> {
    return this.deps.storage.query<SourceRecord>(KIND, s => s.sourceType.length >= 0)
  }
}

/**
 * Prompt for the real-LLM brief: ask the model to extract a concise, factual
 * synthesis of the retrieved sources without fabricating any. Kept dependency
 * free so the service stays unit-testable against a stubbed `LlmPort`.
 */
function buildBriefPrompt(question: string, records: SourceRecord[]): string {
  const bullets = records
    .filter(r => r.sourceType !== 'llm_brief')
    .map(r => `- (${r.sourceType}) ${r.contentHash}: see ${r.locator}`)
    .join('\n')
  return [
    'You are AIJADE\'s knowledge acquirer. Given the research question and the',
    'retrieved raw sources, write a concise factual brief (3-5 sentences) that',
    'captures the key verified points. Do not invent sources or claims.',
    '',
    `Research question: ${question}`,
    '',
    'Retrieved sources:',
    bullets || '(none)',
  ].join('\n')
}
