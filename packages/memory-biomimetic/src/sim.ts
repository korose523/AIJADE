/**
 * Lexical similarity + token-overlap F1.
 *
 * Deliberately dependency-free: a hashed bag-of-words TF-IDF cosine is good
 * enough to separate "which memory is about X" and — crucially — it is held
 * constant* across the gating ON/OFF conditions, so any measured difference
 * comes from the memory dynamics, not from embedding quality.
 *
 * The index stores sparse vectors and precomputed L2 norms, so retrieval does
 * an intersection dot-product against the (few) query tokens instead of a dense
 * multiply over the whole vocabulary.
 */

const STOP = new Set([
  'the',
  'a',
  'an',
  'and',
  'or',
  'but',
  'if',
  'then',
  'else',
  'when',
  'at',
  'by',
  'for',
  'with',
  'about',
  'against',
  'between',
  'into',
  'through',
  'during',
  'before',
  'after',
  'above',
  'below',
  'to',
  'from',
  'up',
  'down',
  'in',
  'out',
  'on',
  'off',
  'over',
  'under',
  'again',
  'further',
  'is',
  'are',
  'was',
  'were',
  'be',
  'been',
  'being',
  'have',
  'has',
  'had',
  'do',
  'does',
  'did',
  'of',
  'this',
  'that',
  'these',
  'those',
  'i',
  'you',
  'he',
  'she',
  'it',
  'we',
  'they',
  'me',
  'him',
  'her',
  'us',
  'them',
  'my',
  'your',
  'his',
  'its',
  'our',
  'their',
  'what',
  'which',
  'who',
  'whom',
  'where',
  'why',
  'how',
  'all',
  'any',
  'both',
  'each',
  'few',
  'more',
  'most',
  'some',
  'such',
  'no',
  'nor',
  'not',
  'only',
  'own',
  'same',
  'so',
  'than',
  'too',
  'very',
  'can',
  'will',
  'just',
  'dont',
  'should',
  'now',
  'im',
  'yeah',
  'yes',
  'got',
  'get',
  'really',
  'like',
  'love',
  'great',
])

export function tokenize(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/)
    .filter(t => t.length > 1 && !STOP.has(t))
}

export interface QueryVec {
  sparse: Map<number, number>
  norm: number
}

export interface LexicalIndex {
  dim: number
  /** Dense vector (vocab-length) — used to populate Episode/Fact.embedding. */
  embed: (text: string) => Float64Array
  denseVec: (id: string) => Float64Array
  /** Sparse tf-idf for a raw query string. */
  querySparse: (text: string) => QueryVec
  /** Cosine of a query (sparse tf-idf) against a stored doc. */
  cosine: (query: QueryVec, id: string) => number
}

export function buildLexicalIndex(docs: { id: string, text: string }[]): LexicalIndex {
  const df = new Map<string, number>()
  const tokenized = docs.map((d) => {
    const t = tokenize(d.text)
    for (const tok of t) df.set(tok, (df.get(tok) ?? 0) + 1)
    return t
  })

  const vocab = [...df.keys()]
  const vidx = new Map(vocab.map((v, i) => [v, i]))
  const N = docs.length
  const idf = new Map(vocab.map(v => [v, Math.log((N + 1) / (df.get(v)! + 1)) + 1]))

  const sparse = new Map<string, Map<number, number>>()
  const norms = new Map<string, number>()

  const weight = (term: string, count: number): { idx: number, w: number } | null => {
    const idx = vidx.get(term)
    if (idx === undefined)
      return null
    return { idx, w: (1 + Math.log(count)) * idf.get(term)! }
  }

  const toSparse = (toks: string[]): { sp: Map<number, number>, norm: number } => {
    const tf = new Map<string, number>()
    for (const t of toks) tf.set(t, (tf.get(t) ?? 0) + 1)
    const sp = new Map<number, number>()
    let norm = 0
    for (const [term, count] of tf) {
      const r = weight(term, count)
      if (!r)
        continue
      sp.set(r.idx, r.w)
      norm += r.w * r.w
    }
    return { sp, norm: Math.sqrt(norm) }
  }

  tokenized.forEach((toks, i) => {
    const { sp, norm } = toSparse(toks)
    sparse.set(docs[i].id, sp)
    norms.set(docs[i].id, norm)
  })

  return {
    dim: vocab.length,
    embed(text: string): Float64Array {
      const v = new Float64Array(vocab.length)
      const { sp } = toSparse(tokenize(text))
      for (const [idx, w] of sp) v[idx] = w
      return v
    },
    denseVec(id: string): Float64Array {
      const v = new Float64Array(vocab.length)
      const sp = sparse.get(id)
      if (sp) {
        for (const [idx, w] of sp) v[idx] = w
      }
      return v
    },
    querySparse(text: string): QueryVec {
      const { sp, norm } = toSparse(tokenize(text))
      return { sparse: sp, norm }
    },
    cosine(query: QueryVec, id: string): number {
      const sp = sparse.get(id)
      const norm = norms.get(id) ?? 0
      if (!sp || norm === 0 || query.norm === 0)
        return 0
      let dot = 0
      for (const [idx, w] of query.sparse) {
        const dw = sp.get(idx)
        if (dw)
          dot += w * dw
      }
      const denom = query.norm * norm
      return denom === 0 ? 0 : dot / denom
    },
  }
}

/** Dense cosine, kept for unit tests. */
export function cosine(a: Float64Array, b: Float64Array): number {
  let dot = 0
  let na = 0
  let nb = 0
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i]
    na += a[i] * a[i]
    nb += b[i] * b[i]
  }
  const denom = Math.sqrt(na) * Math.sqrt(nb)
  return denom === 0 ? 0 : dot / denom
}

/** Token-level F1, the standard LoCoMo factual metric. */
export function tokenF1(pred: string, gold: string): number {
  const p = new Set(tokenize(pred))
  const g = new Set(tokenize(gold))
  if (p.size === 0 && g.size === 0)
    return 1
  if (p.size === 0 || g.size === 0)
    return 0
  let common = 0
  for (const t of p) {
    if (g.has(t))
      common++
  }
  const prec = common / p.size
  const rec = common / g.size
  if (prec + rec === 0)
    return 0
  return (2 * prec * rec) / (prec + rec)
}
