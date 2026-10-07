// Degree-preserving randomization — the configuration-model null distribution.
//
// We reimplement the standard MCMC double-edge swap OURSELVES (no graspologic /
// networkx / graph-library dependency) so the package stays license-clean (MIT)
// and auditable. MOSAIC's "Connectome Randomization" (degree-preserving /
// edge-shuffle) is the methodological inspiration; we borrow the METHOD, not code.
//
// Reproducibility: every random draw is seeded (mulberry32) — this project's
// determinism pre-check requires bit-exact reruns.

export type Edge = readonly [string, string]

export interface Graph {
  readonly nodes: readonly string[]
  readonly edges: readonly Edge[]
}

/** Deterministic, seeded PRNG (mulberry32). */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6D2B79F5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function undirectedKey(e: Edge): string {
  return e[0] <= e[1] ? `${e[0]}\u0000${e[1]}` : `${e[1]}\u0000${e[0]}`
}

function directedKey(e: Edge): string {
  return `${e[0]}\u0000${e[1]}`
}

/**
 * Undirected degree-preserving double-edge swap (MCMC).
 * Swaps (a-b, c-d) -> (a-d, c-b) when that introduces no self-loop and no
 * duplicate edge. Each accepted swap preserves every node's degree, so the
 * returned graph is a configuration-model sample of the input.
 */
export function edgeSwapMCMC(input: Graph, numSwaps: number, rng: () => number): Graph {
  const edges: Edge[] = input.edges.map(e => [e[0], e[1]] as Edge)
  const seen = new Set(edges.map(undirectedKey))
  let accepted = 0
  let attempts = 0
  const maxAttempts = Math.max(numSwaps * 50, numSwaps + 100)
  while (accepted < numSwaps && attempts < maxAttempts) {
    attempts++
    const i = Math.floor(rng() * edges.length)
    const j = Math.floor(rng() * edges.length)
    if (i === j)
      continue
    const [a, b] = edges[i]
    const [c, d] = edges[j]
    if (a === c || a === d || b === c || b === d)
      continue // would create a self-loop / degenerate swap
    const e1: Edge = [a, d]
    const e2: Edge = [c, b]
    const k1 = undirectedKey(e1)
    const k2 = undirectedKey(e2)
    if (seen.has(k1) || seen.has(k2))
      continue
    seen.delete(undirectedKey(edges[i]))
    seen.delete(undirectedKey(edges[j]))
    edges[i] = e1
    edges[j] = e2
    seen.add(k1)
    seen.add(k2)
    accepted++
  }
  return { nodes: [...input.nodes], edges }
}

/**
 * Directed degree-preserving swap. Swaps (a->b, c->d) -> (a->d, c->b), which
 * preserves the out-degree of a,c and the in-degree of b,d. Rejects self-loops
 * (a===d or c===b) and duplicate directed edges.
 */
export function directedEdgeSwapMCMC(input: Graph, numSwaps: number, rng: () => number): Graph {
  const edges: Edge[] = input.edges.map(e => [e[0], e[1]] as Edge)
  const seen = new Set(edges.map(directedKey))
  let accepted = 0
  let attempts = 0
  const maxAttempts = Math.max(numSwaps * 50, numSwaps + 100)
  while (accepted < numSwaps && attempts < maxAttempts) {
    attempts++
    const i = Math.floor(rng() * edges.length)
    const j = Math.floor(rng() * edges.length)
    if (i === j)
      continue
    const [a, b] = edges[i]
    const [c, d] = edges[j]
    if (a === d || c === b)
      continue // self-loop
    const e1: Edge = [a, d]
    const e2: Edge = [c, b]
    const k1 = directedKey(e1)
    const k2 = directedKey(e2)
    if (seen.has(k1) || seen.has(k2))
      continue
    seen.delete(directedKey(edges[i]))
    seen.delete(directedKey(edges[j]))
    edges[i] = e1
    edges[j] = e2
    seen.add(k1)
    seen.add(k2)
    accepted++
  }
  return { nodes: [...input.nodes], edges }
}

/** Convenience: a degree-preserving null-model graph for baseline comparison. */
export function degreePreservingNull(input: Graph, numSwaps: number, seed: number, directed = false): Graph {
  const rng = mulberry32(seed)
  return directed
    ? directedEdgeSwapMCMC(input, numSwaps, rng)
    : edgeSwapMCMC(input, numSwaps, rng)
}
