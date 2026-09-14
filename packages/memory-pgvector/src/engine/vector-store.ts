import { cosineSimilarity } from './embed'

export interface ScoredVector {
  id: string
  score: number
}

/**
 * Pluggable vector index. The default {@link InMemoryVectorStore} keeps
 * everything in RAM and is what the unit tests exercise. A production
 * deployment can supply a pgvector-backed store implementing the same
 * interface (upsert/delete/query/clear/size) without touching the engine.
 */
export interface VectorStore {
  upsert: (id: string, vector: number[]) => void
  delete: (id: string) => void
  query: (vector: number[], topK: number, minScore?: number) => ScoredVector[]
  clear: () => void
  size: () => number
}

export class InMemoryVectorStore implements VectorStore {
  private vectors = new Map<string, number[]>()

  upsert(id: string, vector: number[]): void {
    this.vectors.set(id, vector)
  }

  delete(id: string): void {
    this.vectors.delete(id)
  }

  query(vector: number[], topK: number, minScore = -1): ScoredVector[] {
    const scored: ScoredVector[] = []
    for (const [id, v] of this.vectors) {
      const s = cosineSimilarity(vector, v)
      if (s >= minScore)
        scored.push({ id, score: s })
    }
    scored.sort((a, b) => b.score - a.score)
    return scored.slice(0, topK)
  }

  clear(): void {
    this.vectors.clear()
  }

  size(): number {
    return this.vectors.size
  }
}
