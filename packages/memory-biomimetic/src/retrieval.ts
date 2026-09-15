import type { AffectiveSnapshot, CandidateKind, RetrievalWeights } from './types'

export function jaccard(a: string[], b: string[]): number {
  if (a.length === 0 && b.length === 0)
    return 0
  const sa = new Set(a)
  const sb = new Set(b)
  let inter = 0
  for (const x of sa) {
    if (sb.has(x))
      inter++
  }
  const union = sa.size + sb.size - inter
  return union === 0 ? 0 : inter / union
}

/** Anything that can take part in content deduplication. */
export interface DedupableCandidate {
  kind: CandidateKind
  id: string
  content: string
  createdAt: number
}

export interface DedupResult<T extends DedupableCandidate> {
  kept: T[]
  /** survivor id -> the ids that were collapsed into it. */
  absorbed: Map<string, string[]>
}

/**
 * Collapse candidates whose whitespace-normalised content is identical.
 *
 * `LexicalDistiller` emits exactly one fact per episode and, being lexical,
 * copies the episode's content **verbatim**. Without this collapse every piece
 * of evidence enters the ranking twice — as `e` and as `fact_e` — so a reported
 * `recall@8` is in truth a `recall@4`, and the precision of every K is halved by
 * construction. Measured on LoCoMo: removing the duplicate copies was worth
 * +0.1245 recall@8 on its own.
 *
 * The survivor is chosen by provenance first (`episode` beats the derived
 * `fact`), then by age. Losers are **not** deleted — the caller keeps them in
 * the store for audit and only excludes them from ranking; `absorbed` records
 * which id swallowed which, so a collapsed evidence chain stays explicable.
 */
export function collapseDuplicateContent<T extends DedupableCandidate>(
  items: T[],
): DedupResult<T> {
  const rank: Record<CandidateKind, number> = { episode: 0, fact: 1, procedural: 2, working: 3 }
  const buckets = new Map<string, T[]>()
  const order: string[] = []
  for (const it of items) {
    const key = it.content.trim().replace(/\s+/g, ' ').toLowerCase()
    const bucket = buckets.get(key)
    if (bucket) {
      bucket.push(it)
    }
    else {
      buckets.set(key, [it])
      order.push(key)
    }
  }
  const kept: T[] = []
  const absorbed = new Map<string, string[]>()
  for (const key of order) {
    const bucket = buckets.get(key)!
    if (bucket.length === 1) {
      kept.push(bucket[0])
      continue
    }
    const sorted = [...bucket].sort(
      (a, b) => (rank[a.kind] - rank[b.kind]) || (a.createdAt - b.createdAt),
    )
    kept.push(sorted[0])
    absorbed.set(sorted[0].id, sorted.slice(1).map(x => x.id))
  }
  return { kept, absorbed }
}

export interface ScoreParts {
  similarity: number
  strength: number
  recency: number
  context: number
  /**
   * Presentation-only affect term. The store passes 0 here at retrieval — affect
   * no longer biases the memory score (it is a presentation concern).
   */
  affect: number
}

/**
 * Weighted multi-cue retrieval score — **legacy `'additive'` mode**.
 *
 * Each component is individually squashed into ~[0,1]:
 * - similarity: cosine (0..1)
 * - strength: strength/(1+strength) — compresses the long tail
 * - recency: 1/(1+ageNorm)
 * - context: Jaccard of tag sets
 * - affect: **presentation-only**; the memory path always passes 0 here.
 *
 * ⚠️ The earlier version of this comment claimed that because each component is
 * individually bounded to [0,1], "the weights are comparable". That inference is
 * wrong, and it is the documented origin of a long-standing defect: bounding a
 * component to [0,1] says nothing about **where its mass actually lies**. On the
 * LoCoMo corpus the sparse TF-IDF cosine between a short query and a long
 * utterance occupies roughly 0.05–0.2, while `strength/(1+strength)` sits near
 * 0.5 and `recency` near 1.0 for anything recent. A raw weighted sum with
 * `{1, 0.6, 0.3, 0.4}` therefore ranks almost purely by recency.
 *
 * Use {@link scoreCandidatesStandardized} (the default via
 * `MemoryConfig.retrievalScoreMode`) when the weights are meant to express
 * importance. This function is retained unchanged so that numbers computed
 * before the fix remain reproducible.
 */
export function scoreCandidate(
  similarity: number,
  strengthRaw: number,
  recency: number,
  context: number,
  affect: number,
  w: RetrievalWeights,
): { score: number, parts: ScoreParts } {
  const sStrength = strengthRaw / (1 + strengthRaw)
  const sContext = Math.max(0, Math.min(1, context))
  const sAffect = Math.max(0, affect)
  const score
    = w.similarity * similarity
      + w.strength * sStrength
      + w.recency * recency
      + w.context * sContext
      + w.affect * sAffect
  return { score, parts: { similarity, strength: sStrength, recency, context: sContext, affect: sAffect } }
}

/** One candidate's raw cue values, before weighting and before standardisation. */
export interface RawScoreRow {
  similarity: number
  strengthRaw: number
  recency: number
  context: number
  affect: number
}

export interface StandardizedScore {
  /**
   * Weighted sum of the z-scored components, shifted so the pool minimum is 0
   * (the downstream noise and R-conflict stages are multiplicative, so a
   * negative score would invert their meaning).
   */
  score: number
  /** The saturated but still **raw** component values, for `parts`. */
  rawParts: ScoreParts
  /** The z-scored component values actually multiplied by the weights. */
  z: { similarity: number, strength: number, recency: number, context: number }
}

/**
 * Relevance-commensurable multi-cue score.
 *
 * Every component is z-scored **across the candidate pool** and only then
 * multiplied by the (unchanged) weights. Two properties follow:
 *
 * 1. The weights become interpretable as relative importance. Under the raw sum
 *    they were not: the ranking was dominated by whichever component had the
 *    widest absolute range, which on this corpus means recency.
 * 2. The score is invariant to a per-component affine rescaling of the inputs.
 *    Rescaling cosine, say, can no longer silently re-weight the model.
 *
 * Statistics come from the **pool**, never from `K`, so `retrieve(q, K)` remains
 * a strict prefix of `retrieve(q, K')` for `K < K'` — without which recall@1/2/4/8
 * would not be comparable. A consequence worth stating plainly: scores are
 * pool-relative, so adding memories to a store changes the scores of existing
 * ones. They rank correctly; their absolute values are not portable between
 * stores.
 *
 * A component with zero variance contributes exactly 0 (never NaN/Infinity):
 * "every candidate is equally recent" is not evidence about relevance, and it
 * must not be silently turned into a tie-break by 0/0.
 */
export function scoreCandidatesStandardized(
  rows: RawScoreRow[],
  w: RetrievalWeights,
): StandardizedScore[] {
  const n = rows.length
  if (n === 0)
    return []

  // Saturated components — the same quantities the additive mode weights, so the
  // only difference between the two modes is the scaling, not the inputs.
  const sim: number[] = new Array(n)
  const str: number[] = new Array(n)
  const rec: number[] = new Array(n)
  const ctx: number[] = new Array(n)
  const aff: number[] = new Array(n)
  for (let i = 0; i < n; i++) {
    const r = rows[i]
    sim[i] = r.similarity
    str[i] = r.strengthRaw / (1 + r.strengthRaw)
    rec[i] = r.recency
    ctx[i] = Math.max(0, Math.min(1, r.context))
    aff[i] = Math.max(0, r.affect)
  }

  const zSim = zScore(sim)
  const zStr = zScore(str)
  const zRec = zScore(rec)
  const zCtx = zScore(ctx)

  const out: StandardizedScore[] = new Array(n)
  let min = Number.POSITIVE_INFINITY
  const rawScores: number[] = new Array(n)
  for (let i = 0; i < n; i++) {
    const score
      = w.similarity * zSim[i]
        + w.strength * zStr[i]
        + w.recency * zRec[i]
        + w.context * zCtx[i]
        + w.affect * 0 // affect is presentation-only, as in the additive path
    rawScores[i] = score
    if (score < min)
      min = score
  }
  const shift = min < 0 ? -min : 0
  for (let i = 0; i < n; i++) {
    out[i] = {
      score: rawScores[i] + shift,
      rawParts: {
        similarity: sim[i],
        strength: str[i],
        recency: rec[i],
        context: ctx[i],
        affect: aff[i],
      },
      z: { similarity: zSim[i], strength: zStr[i], recency: zRec[i], context: zCtx[i] },
    }
  }
  return out
}

/**
 * Population z-scores. A zero-variance column maps entirely to 0 rather than
 * 0/0 — see {@link scoreCandidatesStandardized}.
 */
function zScore(xs: number[]): number[] {
  const n = xs.length
  if (n === 0)
    return []
  let mean = 0
  for (const x of xs)
    mean += x
  mean /= n
  let variance = 0
  for (const x of xs) {
    const d = x - mean
    variance += d * d
  }
  variance /= n
  if (!(variance > 0))
    return new Array<number>(n).fill(0)
  const sd = Math.sqrt(variance)
  const out = new Array<number>(n)
  for (let i = 0; i < n; i++)
    out[i] = (xs[i] - mean) / sd
  return out
}

/**
 * Presentation-only affect congruence helper. Kept for expression-layer use;
 * it no longer takes (or needs) a `GatingCoefficients` and is **not** called by
 * the memory `retrieve` path.
 */
export function affectTerm(
  enc: AffectiveSnapshot,
  cur: AffectiveSnapshot,
): number {
  const d
    = Math.abs(enc.valence - cur.valence)
      + Math.abs(enc.arousal - cur.arousal)
      + Math.abs(enc.dominance - cur.dominance)
  return Math.max(0, 1 - d / 3)
}

const NEGATION_CUES = /\b(?:not|never|no|don't|isn't|can't|won't|didn't|doesn't|wouldn't|couldn't|shouldn't|aren't)\b/i

/** Tokens that can act as a "key entity": Capitalised word or any digit-bearing token. */
export function entityTokens(text: string): Set<string> {
  const set = new Set<string>()
  for (const raw of text.split(/[^A-Z0-9]+/i)) {
    if (!raw)
      continue
    if (/^[A-Z][a-z]+$/.test(raw) || /\d/.test(raw))
      set.add(raw.toLowerCase())
  }
  return set
}

export function hasNegation(text: string): boolean {
  return NEGATION_CUES.test(text)
}

/**
 * R-conflict detection (retrieval conflict penalty, spec §3).
 *
 * Two candidates conflict when they share a key entity (a token matching
 * /^[A-Z][a-z]+$/ or any digit-bearing token) AND carry **opposing polarity**
 * — one contains a negation cue ("not/never/no/don't/isn't/can't/won't/…")
 * while the other does not, on the same entity.
 */
export function detectConflict(a: string, b: string): boolean {
  const ea = entityTokens(a)
  const eb = entityTokens(b)
  let shared = false
  for (const t of ea) {
    if (eb.has(t)) {
      shared = true
      break
    }
  }
  if (!shared)
    return false
  return hasNegation(a) !== hasNegation(b)
}
