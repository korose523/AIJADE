/**
 * Real retrieval-backend adapter — backs {@link SearchPort} with AIJADE's own
 * layered-memory engine from `@proj-aijade/memory-pgvector`. This is the genuine
 * vector-retrieval backend: a corpus (locator / sourceType / content) is
 * ingested as episodic memories, and `search` performs a Scope-Recall ranked
 * retrieval, returning the top matches as {@link RawHit}s (untrusted external
 * content, ready to be quarantined by KnowledgeAcquirer).
 *
 * The engine ships with a dependency-free hashed embedder + in-memory vector
 * store; swap in a real `EmbeddingFn` + pgvector `VectorStore` for production
 * semantic recall. The corpus can also be loaded from a local directory of
 * documents, making this a real on-disk knowledge base.
 */

import type { MemoryScope } from '@proj-aijade/memory-pgvector/engine'

import type { RawHit, SearchPort } from '../ports'

import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

import { createHashEmbedder, LayeredMemory } from '@proj-aijade/memory-pgvector/engine'

export interface CorpusItem {
  locator: string
  sourceType: string
  content: string
}

export interface PgVectorSearchOptions {
  /** Pre-seed corpus. */
  corpus?: CorpusItem[]
  /** Recalled hit cap. @default 8 */
  limit?: number
  /** Minimum cosine similarity for long-term candidates. */
  minSimilarity?: number
  /** Load a corpus from a directory of .md/.txt/.json files (sync). */
  searchDir?: string
}

/** Read a directory of documents into a corpus (locator = absolute path). */
export function corpusFromDirSync(dir: string): CorpusItem[] {
  if (!existsSync(dir))
    return []
  const items: CorpusItem[] = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    let stat
    try {
      stat = statSync(full)
    }
    catch {
      continue
    }
    if (!stat.isFile())
      continue
    const lower = name.toLowerCase()
    if (!lower.endsWith('.md') && !lower.endsWith('.txt') && !lower.endsWith('.json'))
      continue
    try {
      const content = readFileSync(full, 'utf8').trim()
      if (content)
        items.push({ locator: full, sourceType: lower.endsWith('.json') ? 'data' : 'doc', content })
    }
    catch {
      // Skip unreadable files.
    }
  }
  return items
}

export class PgVectorSearchAdapter implements SearchPort {
  private readonly engine: LayeredMemory
  private readonly limit: number
  private readonly minSimilarity?: number
  /** Maps ingested verbatim content → corpus metadata (for locator/sourceType). */
  private readonly meta = new Map<string, { locator: string, sourceType: string }>()

  constructor(opts: PgVectorSearchOptions = {}) {
    this.engine = new LayeredMemory({ embedder: createHashEmbedder() })
    this.limit = opts.limit ?? 8
    this.minSimilarity = opts.minSimilarity
    if (opts.searchDir)
      this.seedAll(corpusFromDirSync(opts.searchDir))
    if (opts.corpus)
      this.seedAll(opts.corpus)
  }

  /** Ingest a single corpus item as an episodic memory under its sourceType scope. */
  seed(item: CorpusItem): void {
    const scope = item.sourceType as MemoryScope
    void this.engine.ingestEpisodic(item.content, { scope, role: 'event' })
    this.meta.set(item.content, { locator: item.locator, sourceType: item.sourceType })
  }

  private seedAll(items: CorpusItem[]): void {
    for (const it of items)
      this.seed(it)
  }

  async search(query: string, sourceTypes: string[]): Promise<RawHit[]> {
    const scopes = sourceTypes.length ? (sourceTypes as MemoryScope[]) : undefined
    const results = await this.engine.recall(query, {
      scopes,
      limit: this.limit,
      includeRecent: true,
      minSimilarity: this.minSimilarity,
    })
    const now = Date.now()
    const hits: RawHit[] = []
    for (const r of results) {
      const m = this.meta.get(r.text)
      hits.push({
        locator: m?.locator ?? `aijade://memory/${r.id}`,
        sourceType: m?.sourceType ?? r.scope,
        content: r.text,
        fetchedAt: now,
      })
    }
    return hits
  }

  /** Expose the backing engine (introspection / tests). */
  get engineRef(): LayeredMemory {
    return this.engine
  }
}
