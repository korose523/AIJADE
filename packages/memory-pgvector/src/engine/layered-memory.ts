import type { EmbeddingFn } from './embed'
import type {
  EpisodicMemory,
  LongTermMemory,
  MemoryScope,
  MemoryStats,
  RecallOptions,
  RecallResult,
  SummaryMemory,
  TimeRange,
} from './types'
import type { VectorStore } from './vector-store'

import { cosineSimilarity, createHashEmbedder } from './embed'
import { rankLongTerm } from './scope-recall'
import { InMemoryVectorStore } from './vector-store'

/** Turns a batch of episodic entries into one summary string. */
export type Summarizer = (entries: Array<{ text: string, role?: string }>) => string | Promise<string>

/** Turns a summary string into discrete long-term facts. */
export type Distiller = (summaryText: string) => string[] | Promise<string[]>

export interface LayeredMemoryOptions {
  embedder?: EmbeddingFn
  vectorStore?: VectorStore
  /** Clock for testability. Defaults to `Date.now`. */
  now?: () => number
  /** Half-life of long-term salience decay (ms). Default 30 days. */
  halfLifeMs?: number
  /** Max long-term memories retained after {@link prune} (capacity). Default 1000. */
  longTermCapacity?: number
  /** Episodic entries per scope kept before {@link compact} triggers. Default 20. */
  episodicCompactThreshold?: number
  summarizer?: Summarizer
  distiller?: Distiller
}

let idCounter = 0
function genId(prefix: string): string {
  idCounter += 1
  return `${prefix}_${Date.now().toString(36)}_${idCounter.toString(36)}`
}

function overlaps(first: number, last: number, range: Partial<TimeRange>): boolean {
  if (range.firstSeen != null && last < range.firstSeen)
    return false
  if (range.lastSeen != null && first > range.lastSeen)
    return false
  return true
}

/**
 * Layered memory engine for AIJADE.
 *
 * Three tiers, in the spirit of AkaneCompanionLab / the "长期记忆" companion
 * videos:
 *
 * 1. **Episodic** — verbatim recent messages (like AIJADE `RawMessage`s), kept
 *    until they are compacted or expire.
 * 2. **Summary** — compacted windows (like the `summary` history item from
 *    `compactConversationEntries`, with optional turn indices).
 * 3. **Long-term** — distilled, embedded facts with a time range and a
 *    reinforcement counter, recalled via {@link recall} using Scope-Recall.
 *
 * The engine is pure TypeScript with no external dependencies, so it is fully
 * unit-testable without a live database. Swap in a pgvector `VectorStore` and a
 * real `EmbeddingFn` for production.
 */
export class LayeredMemory {
  private episodic: EpisodicMemory[] = []
  private summaries: SummaryMemory[] = []
  private longTerm: LongTermMemory[] = []
  private readonly embedder: EmbeddingFn
  private readonly store: VectorStore
  private readonly now: () => number
  private readonly halfLifeMs: number
  private readonly longTermCapacity: number
  private readonly episodicCompactThreshold: number
  private readonly summarizer: Summarizer
  private readonly distiller: Distiller

  constructor(opts: LayeredMemoryOptions = {}) {
    this.embedder = opts.embedder ?? createHashEmbedder()
    this.store = opts.vectorStore ?? new InMemoryVectorStore()
    this.now = opts.now ?? Date.now
    this.halfLifeMs = opts.halfLifeMs ?? 30 * 24 * 60 * 60 * 1000
    this.longTermCapacity = opts.longTermCapacity ?? 1000
    this.episodicCompactThreshold = opts.episodicCompactThreshold ?? 20
    this.summarizer
      = opts.summarizer ?? (entries => entries.map(e => `${e.role ?? 'user'}: ${e.text}`).join('\n'))
    this.distiller
      = opts.distiller ?? (text => text.split(/(?<=[.!?。！？])\s*/).map(s => s.trim()).filter(Boolean))
  }

  /** Ingest a verbatim recent message into the episodic tier. */
  async ingestEpisodic(
    text: string,
    opts: { scope: MemoryScope, role?: EpisodicMemory['role'], ttlMs?: number },
  ): Promise<EpisodicMemory> {
    const now = this.now()
    const mem: EpisodicMemory = {
      id: genId('epi'),
      tier: 'episodic',
      scope: opts.scope,
      role: opts.role,
      text,
      createdAt: now,
      expiresAt: opts.ttlMs != null ? now + opts.ttlMs : undefined,
    }
    this.episodic.push(mem)
    return mem
  }

  /**
   * Compact episodic memories per scope once they exceed the threshold,
   * producing a `SummaryMemory` and distilling long-term facts from it.
   *
   * Pass `{ force: true }` (or `createLayeredMemoryPort`'s `maybeCompact`) to
   * compact regardless of the engine threshold — useful when the caller owns a
   * smaller, pipeline-specific threshold.
   */
  async compact(
    scope?: MemoryScope | { scope?: MemoryScope, force?: boolean },
  ): Promise<SummaryMemory[]> {
    const opts = typeof scope === 'string' ? { scope } : (scope ?? {})
    const force = opts.force ?? false
    const created: SummaryMemory[] = []
    const scopes = opts.scope ? [opts.scope] : [...new Set(this.episodic.map(e => e.scope))]

    for (const sc of scopes) {
      const items = this.episodic.filter(e => e.scope === sc)
      if (!force && items.length <= this.episodicCompactThreshold)
        continue

      const text = await this.summarizer(items.map(i => ({ text: i.text, role: i.role })))
      const summary: SummaryMemory = {
        id: genId('sum'),
        tier: 'summary',
        scope: sc,
        text,
        createdAt: this.now(),
        sourceIds: items.map(i => i.id),
      }
      this.summaries.push(summary)

      const facts = await this.distiller(text)
      for (const fact of facts)
        await this.addLongTerm(fact, sc, items.map(i => i.id))

      const removeIds = new Set(items.map(i => i.id))
      this.episodic = this.episodic.filter(e => !removeIds.has(e.id))
      created.push(summary)
    }

    return created
  }

  private async addLongTerm(text: string, scope: MemoryScope, sourceIds: string[]): Promise<LongTermMemory> {
    const now = this.now()
    const embedding = await this.embedder(text)

    // Merge near-identical facts within the same scope instead of duplicating.
    const dup = this.longTerm.find(
      m => m.scope === scope && cosineSimilarity(m.embedding, embedding) > 0.98,
    )
    if (dup) {
      dup.timeRange.lastSeen = now
      dup.sourceIds = [...new Set([...dup.sourceIds, ...sourceIds])]
      return dup
    }

    const lt: LongTermMemory = {
      id: genId('lt'),
      tier: 'longterm',
      scope,
      text,
      embedding,
      timeRange: { firstSeen: now, lastSeen: now },
      salience: 0,
      createdAt: now,
      sourceIds,
    }
    this.longTerm.push(lt)
    this.store.upsert(lt.id, embedding)
    return lt
  }

  /**
   * Recall memories relevant to `query`.
   *
   * - Long-term tier is ranked with Scope-Recall (scope filter × time decay ×
   *   reinforcement boost) and, when `reinforce` is on, each returned long-term
   *   memory is reinforced (salience +1, `lastSeen` bumped).
   * - The recent tiers (episodic + summary within scope) are included and
   *   ranked by recency so the most current context is always available.
   */
  async recall(query: string, opts: RecallOptions = {}): Promise<RecallResult[]> {
    const {
      scopes,
      timeRange,
      limit = 10,
      minSimilarity,
      reinforce = true,
      includeRecent = true,
    } = opts

    const now = this.now()
    const queryEmbedding = await this.embedder(query)
    const results: RecallResult[] = []

    const ranked = rankLongTerm(queryEmbedding, this.longTerm, {
      scopes,
      timeRange,
      minSimilarity,
      now,
      halfLifeMs: this.halfLifeMs,
    })
    for (const r of ranked) {
      if (reinforce) {
        r.memory.salience += 1
        r.memory.lastRecalledAt = now
        r.memory.timeRange.lastSeen = now
      }
      results.push({
        id: r.memory.id,
        tier: 'longterm',
        scope: r.memory.scope,
        text: r.memory.text,
        score: r.score,
        similarity: r.similarity,
        salience: r.memory.salience,
        timeRange: r.memory.timeRange,
      })
    }

    if (includeRecent) {
      const scopeSet = scopes && scopes.length ? new Set(scopes) : null
      const recent: Array<{ m: EpisodicMemory | SummaryMemory, score: number }> = []

      for (const e of this.episodic) {
        if (scopeSet && !scopeSet.has(e.scope))
          continue
        if (timeRange && !overlaps(e.createdAt, e.createdAt, timeRange))
          continue
        const age = now - e.createdAt
        recent.push({ m: e, score: Math.max(0, 1 - age / (this.halfLifeMs * 2)) })
      }
      for (const s of this.summaries) {
        if (scopeSet && !scopeSet.has(s.scope))
          continue
        if (timeRange && !overlaps(s.createdAt, s.createdAt, timeRange))
          continue
        const age = now - s.createdAt
        recent.push({ m: s, score: Math.max(0, 0.85 - age / (this.halfLifeMs * 2)) })
      }

      recent.sort((a, b) => b.score - a.score)
      for (const r of recent) {
        results.push({
          id: r.m.id,
          tier: r.m.tier,
          scope: r.m.scope,
          text: r.m.text,
          score: r.score,
        })
      }
    }

    results.sort((a, b) => b.score - a.score)
    return results.slice(0, limit)
  }

  /**
   * Drop expired episodic memories and trim the long-term tier to capacity
   * (keeping the most salient / recently seen).
   */
  prune(opts: { keepEphemeral?: boolean } = {}): { prunedEpisodic: number, prunedLongTerm: number } {
    const now = this.now()
    let prunedEpisodic = 0

    if (!opts.keepEphemeral) {
      const before = this.episodic.length
      this.episodic = this.episodic.filter(e => e.expiresAt == null || e.expiresAt > now)
      prunedEpisodic = before - this.episodic.length
    }

    let prunedLongTerm = 0
    if (this.longTerm.length > this.longTermCapacity) {
      this.longTerm.sort((a, b) => b.salience - a.salience || b.timeRange.lastSeen - a.timeRange.lastSeen)
      const removed = this.longTerm.splice(this.longTermCapacity)
      for (const m of removed)
        this.store.delete(m.id)
      prunedLongTerm = removed.length
    }

    return { prunedEpisodic, prunedLongTerm }
  }

  stats(): MemoryStats {
    return {
      episodic: this.episodic.length,
      summaries: this.summaries.length,
      longTerm: this.longTerm.length,
      vectorStoreSize: this.store.size(),
    }
  }

  /** Test/introspection helper: all long-term memories (unsorted). */
  getLongTerm(): LongTermMemory[] {
    return this.longTerm
  }
}
