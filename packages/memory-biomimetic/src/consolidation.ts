import type { Episode, SemanticFact } from './types'

/**
 * Turns a cluster of episodes into one or more semantic facts.
 *
 * The default {@link LexicalDistiller} is deterministic and dependency-free
 * (it copies content and carries provenance/affect/context forward). A real
 * implementation would call an LLM to summarise and deduplicate — see
 * `llm-distiller.ts`. The interface is what the store depends on, so the
 * dynamics experiment never has to touch a model.
 */
export interface Distiller {
  distill: (episodes: Episode[]) => Promise<SemanticFact[]>
}

export class LexicalDistiller implements Distiller {
  async distill(episodes: Episode[]): Promise<SemanticFact[]> {
    // Per-episode consolidation: each episode becomes one fact, preserving
    // provenance. (Clustering + LLM summarisation is a later enhancement;
    // per-episode keeps the ablation's provenance exact.)
    return episodes.map((e): SemanticFact => ({
      id: `fact_${e.id}`,
      content: e.content,
      derivedFrom: [e.id],
      createdAt: e.createdAt,
      lastAccessedAt: e.createdAt,
      accessCount: 0,
      confidence: 1,
      baseStrength: e.baseStrength,
      durability: e.durability,
      contextTags: e.context.tags,
      salience: e.encoding.salience,
      affect: e.encoding.affect,
      memoryType: 'semantic',
      status: 'active',
      validTime: {},
    }))
  }
}
