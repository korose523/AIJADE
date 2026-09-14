import type { AffectiveSnapshot, RetrievalWeights } from './types'

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
 * Weighted multi-cue retrieval score.
 *
 * Every component is normalised to ~[0,1] so the weights are comparable:
 * - similarity: cosine (already 0..1)
 * - strength: strength/(1+strength) — compresses the long tail
 * - recency: 1/(1+ageNorm)
 * - context: Jaccard of tag sets
 * - affect: **presentation-only**; the memory path always passes 0 here.
 *
 * Under NO_GATING the context term's coefficient is 0 and the caller passes
 * affect=0, leaving pure similarity + strength + recency — again the control.
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
