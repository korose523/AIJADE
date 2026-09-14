/**
 * Embedding utilities.
 *
 * The default {@link createHashEmbedder} is a deterministic, dependency-free
 * bag-of-words hashed embedder. It is NOT semantically rich, but it is stable
 * and good enough for unit tests and local demos without pulling in a model.
 *
 * In production you should inject a real embedding function (e.g. via
 * `@xsai/embeddings` or a local `candle` model) through
 * {@link LayeredMemoryOptions.embedder}.
 */

export type EmbeddingFn = (text: string) => number[] | Promise<number[]>

/**
 * Create a deterministic hashed bag-of-words embedder.
 *
 * @param dimension embedding vector size
 * @param seed hashing seed
 */
export function createHashEmbedder(dimension = 256, seed = 0x9E3779B9): EmbeddingFn {
  return (text: string): number[] => {
    const vec = new Array<number>(dimension).fill(0)
    const tokens = text.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []
    for (const token of tokens) {
      let h = seed ^ token.length
      for (let i = 0; i < token.length; i++)
        h = Math.imul(h ^ token.charCodeAt(i), 0x85EBCA6B)

      const idx = (h >>> 0) % dimension
      vec[idx] += 1
    }

    let norm = 0
    for (const v of vec)
      norm += v * v
    norm = Math.sqrt(norm) || 1
    for (let i = 0; i < dimension; i++)
      vec[i] /= norm

    return vec
  }
}

/** Cosine similarity of two equal-length vectors, range [-1, 1]. */
export function cosineSimilarity(a: number[], b: number[]): number {
  const n = Math.min(a.length, b.length)
  let dot = 0
  let na = 0
  let nb = 0
  for (let i = 0; i < n; i++) {
    dot += a[i] * b[i]
    na += a[i] * a[i]
    nb += b[i] * b[i]
  }
  const denom = Math.sqrt(na) * Math.sqrt(nb)
  return denom === 0 ? 0 : dot / denom
}
