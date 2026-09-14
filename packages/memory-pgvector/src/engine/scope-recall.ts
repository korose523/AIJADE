import type { LongTermMemory, TimeRange } from './types'

import { cosineSimilarity } from './embed'

/**
 * Exponential time decay with a half-life.
 *
 * A memory seen `halfLifeMs` ago scores 0.5; twice that ago scores 0.25, etc.
 * Unseen memories (age 0) score 1. Mirrors the "memories fade unless
 * reinforced" behaviour described in the reference companion projects.
 */
export function timeDecay(lastSeen: number, now: number, halfLifeMs: number): number {
  if (halfLifeMs <= 0)
    return 1
  const age = Math.max(0, now - lastSeen)
  return 2 ** (-age / halfLifeMs)
}

/**
 * Salience boost from reinforcement.
 *
 * Each recall increments {@link LongTermMemory.salience}, so a memory recalled
 * `k` times scores roughly `1 + log2(1 + k)`× higher — capped so a single
 * over-recalled fact cannot dominate forever. This is the "加固" mechanism
 * from AkaneCompanionLab.
 */
export function reinforcementBoost(salience: number, cap = 4): number {
  return Math.min(cap, 1 + Math.log2(1 + Math.max(0, salience)))
}

export interface RankLongTermOptions {
  scopes?: string[]
  timeRange?: Partial<TimeRange>
  minSimilarity?: number
  now: number
  halfLifeMs: number
}

export interface RankedLongTerm {
  memory: LongTermMemory
  similarity: number
  score: number
}

/**
 * Scope-Recall: filter long-term memories by scope + time window, then rank by
 * `similarity × timeDecay × reinforcementBoost`.
 *
 * This is the core of the "structured, scoped recall" idea (Hermes
 * Scope-Recall / AkaneCompanionLab) — instead of returning the top-K most
 * similar vectors globally, we only consider memories relevant to the current
 * scope/context and weight them by freshness and how often they have mattered.
 */
export function rankLongTerm(
  queryEmbedding: number[],
  memories: LongTermMemory[],
  opts: RankLongTermOptions,
): RankedLongTerm[] {
  const scopeSet = opts.scopes && opts.scopes.length ? new Set(opts.scopes) : null
  const out: RankedLongTerm[] = []

  for (const m of memories) {
    if (scopeSet && !scopeSet.has(m.scope))
      continue

    if (opts.timeRange) {
      const { firstSeen, lastSeen } = opts.timeRange
      if (firstSeen != null && m.timeRange.lastSeen < firstSeen)
        continue
      if (lastSeen != null && m.timeRange.firstSeen > lastSeen)
        continue
    }

    const similarity = cosineSimilarity(queryEmbedding, m.embedding)
    if (opts.minSimilarity != null && similarity < opts.minSimilarity)
      continue

    const td = timeDecay(m.timeRange.lastSeen, opts.now, opts.halfLifeMs)
    const boost = reinforcementBoost(m.salience)
    out.push({ memory: m, similarity, score: similarity * td * boost })
  }

  out.sort((a, b) => b.score - a.score)
  return out
}
