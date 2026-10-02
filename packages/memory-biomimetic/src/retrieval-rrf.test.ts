import type { RawScoreRow } from './retrieval'
import type { MemoryConfig } from './types'

import { describe, expect, it } from 'vitest'

import {
  competitionRanksDesc,
  RRF_K,
  scoreCandidate,
  scoreCandidatesRRF,
  scoreCandidatesStandardized,
} from './retrieval'
import { BioticMemory } from './store'
import {
  CORRECTED_RETRIEVAL_WEIGHTS,
  DEFAULT_GATING,
  DEFAULT_MEMORY_CONFIG,
  DEFAULT_RETRIEVAL_WEIGHTS,
  NO_GATING,
} from './types'

const W = DEFAULT_RETRIEVAL_WEIGHTS
const DAY = 86_400_000

function row(over: Partial<RawScoreRow> = {}): RawScoreRow {
  return { similarity: 0, strengthRaw: 0, recency: 0, context: 0, affect: 0, ...over }
}

/** Indices ordered by score descending; input order breaks score ties. */
function ranking(scores: number[]): number[] {
  return scores
    .map((s, i) => ({ s, i }))
    .sort((a, b) => b.s - a.s || a.i - b.i)
    .map(x => x.i)
}

function mkMem(
  gating: MemoryConfig['gating'],
  now: number,
  override: Partial<MemoryConfig> = {},
): BioticMemory {
  return new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, gating, ...override }, now)
}

/**
 * The pool used by the mode-contrast tests.
 *
 * `A` is the **most similar and the least recent** candidate — an extreme,
 * isolated outlier in similarity (0.90 against a tight 0.27–0.30 cluster) while
 * sitting mid-pack on every other cue. `B…E` are consistently ordered, best to
 * worst, on recency / strength / context. That is the shape the J5/P4 defect has:
 * one candidate wins big on relevance cue and loses on the non-relevance ones.
 */
const CONTRAST_POOL: { id: string, row: RawScoreRow }[] = [
  { id: 'A', row: row({ similarity: 0.90, strengthRaw: 1, recency: 0.50, context: 0.3 }) },
  { id: 'B', row: row({ similarity: 0.30, strengthRaw: 5, recency: 0.90, context: 0.9 }) },
  { id: 'C', row: row({ similarity: 0.29, strengthRaw: 4, recency: 0.85, context: 0.8 }) },
  { id: 'D', row: row({ similarity: 0.28, strengthRaw: 3, recency: 0.80, context: 0.7 }) },
  { id: 'E', row: row({ similarity: 0.27, strengthRaw: 2, recency: 0.75, context: 0.6 }) },
]

const contrastIds = (order: number[]): string[] => order.map(i => CONTRAST_POOL[i].id)

describe('the default did not move — RRF is opt-in only', () => {
  it('the default retrievalScoreMode is still standardized', () => {
    // Hard constraint (H2c): an already-published claim depends on the default
    // path being byte-identical. If this flips, every published recall@K number
    // silently changes meaning.
    expect(DEFAULT_MEMORY_CONFIG.retrievalScoreMode).toBe('standardized')
  })

  it('a two-candidate fusion is hand-checkable, and is a rank rule not a sum rule', () => {
    const out = scoreCandidatesRRF([row({ similarity: 1 }), row({ similarity: 2 })], W)
    // similarity ranks: candidate 1 → 1, candidate 0 → 2. Every other component
    // is constant across the pool, so all four of the remaining rank terms are
    // the two-way tie at (1 + 2) / 2 = 1.5.
    const tied = (W.strength + W.recency + W.context) / (RRF_K + 1.5)
    expect(out[0].z.similarity).toBeCloseTo(W.similarity / (RRF_K + 2), 12)
    expect(out[1].z.similarity).toBeCloseTo(W.similarity / (RRF_K + 1), 12)
    expect(out[0].score).toBeCloseTo(W.similarity / (RRF_K + 2) + tied, 12)
    expect(out[1].score).toBeCloseTo(W.similarity / (RRF_K + 1) + tied, 12)
    // Doubling similarity bought exactly one rank, i.e. 1/61 − 1/62 — not double
    // the contribution. That is the whole difference from the additive rule.
    expect(out[1].score - out[0].score).toBeCloseTo(W.similarity * (1 / 61 - 1 / 62), 12)
  })
})

describe('scoreCandidatesRRF — scale invariance (the point of the mode)', () => {
  // Three candidates spanning the dimensional mismatch: high similarity but weak
  // on every other cue, versus mediocre similarity but strong elsewhere.
  const rows = [
    row({ similarity: 0.05, strengthRaw: 3, recency: 1.0, context: 0.1 }),
    row({ similarity: 0.20, strengthRaw: 1, recency: 0.5, context: 0.9 }),
    row({ similarity: 0.30, strengthRaw: 0.1, recency: 0.1, context: 0.0 }),
  ]
  const scale100 = rows.map(r => row({ ...r, similarity: r.similarity * 100 }))
  const affine = rows.map(r => row({ ...r, similarity: 3 * r.similarity + 7 }))

  it('is invariant to multiplying a component by 100', () => {
    // Ranks are unchanged, so the scores must be *bit-identical*, not merely
    // close — that is what "the magnitude is never read" buys.
    expect(scoreCandidatesRRF(scale100, W).map(s => s.score))
      .toEqual(scoreCandidatesRRF(rows, W).map(s => s.score))
  })

  it('is invariant to an affine rescale of a component', () => {
    expect(scoreCandidatesRRF(affine, W).map(s => s.score))
      .toEqual(scoreCandidatesRRF(rows, W).map(s => s.score))
  })

  it('— whereas the additive mode is NOT, which is why this mode exists', () => {
    const add = (rs: RawScoreRow[]) =>
      rs.map(r => scoreCandidate(r.similarity, r.strengthRaw, r.recency, r.context, r.affect, W).score)
    const base = ranking(add(rows))
    expect(ranking(add(scale100))).not.toEqual(base)
    expect(ranking(add(affine))).not.toEqual(base)
    // …and the RRF ranking is stable across all three.
    const rrfBase = ranking(scoreCandidatesRRF(rows, W).map(s => s.score))
    expect(ranking(scoreCandidatesRRF(scale100, W).map(s => s.score))).toEqual(rrfBase)
    expect(ranking(scoreCandidatesRRF(affine, W).map(s => s.score))).toEqual(rrfBase)
  })
})

describe('scoreCandidatesRRF — how it differs from the z-score mode', () => {
  it('reorders an isolated similarity outlier relative to z-scoring', () => {
    const rows = CONTRAST_POOL.map(p => p.row)
    const std = contrastIds(ranking(scoreCandidatesStandardized(rows, W).map(s => s.score)))
    const rrf = contrastIds(ranking(scoreCandidatesRRF(rows, W).map(s => s.score)))

    // Not merely "they can differ": the two modes genuinely disagree here, and
    // the disagreement is the substantively interesting one — `A` (best on
    // similarity, worst on recency) is pushed *down* by z-scoring, because a
    // single extreme value inflates the standard deviation and shrinks
    // everyone else's z-score, and *up* by RRF, for which an outlier is worth
    // exactly one rank step and no more.
    expect(std).toEqual(['B', 'C', 'D', 'A', 'E'])
    expect(rrf).toEqual(['B', 'C', 'A', 'D', 'E'])
    expect(std).not.toEqual(rrf)
  })

  it('honours a weight of 0 the same way the other modes do', () => {
    const rows = CONTRAST_POOL.map(p => p.row)
    // CORRECTED_RETRIEVAL_WEIGHTS zeroes `recency`; RRF must then contribute
    // exactly 0 from that component.
    const out = scoreCandidatesRRF(rows, CORRECTED_RETRIEVAL_WEIGHTS)
    for (const s of out)
      expect(s.z.recency).toBe(0)
    // Worth noting honestly: the overall order is unchanged here — `A` sits 3rd
    // either way, because under RRF its lift comes from holding rank 1 in
    // similarity, not from recency. Zeroing a weight removes a term; it does not
    // automatically reorder a pool whose ranks are already consistent.
    expect(contrastIds(ranking(out.map(s => s.score))))
      .toEqual(['B', 'C', 'A', 'D', 'E'])
  })

  it('gives `affect` no vote at all, as in the other two modes', () => {
    const withAffect = CONTRAST_POOL.map(p => row({ ...p.row, affect: 1 }))
    expect(scoreCandidatesRRF(withAffect, W).map(s => s.score))
      .toEqual(scoreCandidatesRRF(CONTRAST_POOL.map(p => p.row), W).map(s => s.score))
  })
})

describe('scoreCandidatesRRF — shape and bookkeeping', () => {
  it('scores are the sum of the per-component rank contributions carried in `z`', () => {
    const out = scoreCandidatesRRF(CONTRAST_POOL.map(p => p.row), W)
    for (const s of out) {
      expect(s.score).toBeCloseTo(s.z.similarity + s.z.strength + s.z.recency + s.z.context, 12)
      // `z` is a rank contribution here, not a z-score: always in (0, w_c/k].
      for (const v of Object.values(s.z)) {
        expect(v).toBeGreaterThan(0)
        expect(v).toBeLessThanOrEqual(W.similarity / RRF_K)
      }
    }
  })

  it('uses the pool-saturated inputs, identically to the standardized mode', () => {
    const rows = [row({ similarity: 0.4, strengthRaw: 3, recency: 0.5, context: 2, affect: 0.7 })]
    const a = scoreCandidatesRRF(rows, W)[0].rawParts
    const b = scoreCandidatesStandardized(rows, W)[0].rawParts
    expect(a).toEqual(b)
    expect(a.strength).toBeCloseTo(0.75, 12) // 3/(1+3)
    expect(a.context).toBe(1) // clamped
    expect(a.affect).toBe(0.7) // carried for explanation, weighted by 0
  })

  it('is non-negative — the downstream noise and conflict stages are multiplicative', () => {
    for (const s of scoreCandidatesRRF(CONTRAST_POOL.map(p => p.row), W))
      expect(s.score).toBeGreaterThan(0)
  })

  it('yields finite scores when a component has zero variance', () => {
    const flat = Array.from({ length: 4 }, (_, i) =>
      row({ similarity: i * 0.1, strengthRaw: 1, recency: 0.5, context: 0.2 }))
    for (const s of scoreCandidatesRRF(flat, W))
      expect(Number.isFinite(s.score)).toBe(true)
  })

  it('uses the standard damping constant k = 60, overridable by argument', () => {
    expect(RRF_K).toBe(60)
    const rows = CONTRAST_POOL.map(p => p.row)
    const def = scoreCandidatesRRF(rows, W)
    const k1 = scoreCandidatesRRF(rows, W, 1)
    expect(def.map(s => s.score)).not.toEqual(k1.map(s => s.score))
    // k = 1 makes a single rank step worth much more, so the spread widens.
    const spread = (xs: number[]) => Math.max(...xs) - Math.min(...xs)
    expect(spread(k1.map(s => s.score))).toBeGreaterThan(spread(def.map(s => s.score)))
  })

  it('handles an empty pool', () => {
    expect(scoreCandidatesRRF([], W)).toEqual([])
  })
})

describe('competitionRanksDesc — tie policy', () => {
  it('gives tied candidates the mean of the ranks they span', () => {
    expect(competitionRanksDesc([0.9, 0.5, 0.5, 0.5, 0.1])).toEqual([1, 3, 3, 3, 5])
    expect(competitionRanksDesc([0.9, 0.9, 0.5])).toEqual([1.5, 1.5, 3])
    expect(competitionRanksDesc([0.2, 0.2, 0.2])).toEqual([2, 2, 2])
    expect(competitionRanksDesc([1])).toEqual([1])
    expect(competitionRanksDesc([])).toEqual([])
  })

  it('is independent of the input order of tied candidates', () => {
    const a = competitionRanksDesc([0.5, 0.9, 0.5])
    const b = competitionRanksDesc([0.5, 0.9, 0.5])
    expect(a).toEqual(b)
    // The same multiset in a different order yields the same rank per value.
    const shuffled = competitionRanksDesc([0.9, 0.5, 0.5])
    expect(shuffled[0]).toBe(1)
    expect(shuffled[1]).toBe(2.5)
    expect(shuffled[2]).toBe(2.5)
  })

  it('so a component tie contributes the same to every tied candidate', () => {
    // Ties are worth stating plainly: RRF cannot break a component-level tie, it
    // can only aggregate the remaining components' evidence.
    const tied = [
      row({ similarity: 0.5, strengthRaw: 3 }),
      row({ similarity: 0.5, strengthRaw: 1 }),
      row({ similarity: 0.5, strengthRaw: 0.2 }),
    ]
    const out = scoreCandidatesRRF(tied, W)
    expect(out[0].z.similarity).toBeCloseTo(W.similarity / (RRF_K + 2), 12)
    expect(out[1].z.similarity).toBeCloseTo(W.similarity / (RRF_K + 2), 12)
    expect(out[2].z.similarity).toBeCloseTo(W.similarity / (RRF_K + 2), 12)
    // The strength ranks break the overall tie.
    expect(ranking(out.map(s => s.score))).toEqual([0, 1, 2])
  })
})

describe('retrieve under `rrf` — the prefix invariant', () => {
  it('retrieve(q, 8) begins with exactly retrieve(q, 4), as it must for recall@K', () => {
    // Ranks are computed over the whole candidate pool, never over a top-K
    // window, and the R-conflict rerank head is a constant — so K cannot change
    // the ordering. Without this, recall@1/2/4/8 would not be comparable.
    const m = mkMem(DEFAULT_GATING, 30 * DAY, { retrievalScoreMode: 'rrf' })
    for (let i = 0; i < 12; i++) {
      m.encode({
        id: `e${i}`,
        content: `Episode number ${i} concerning subject ${i} with detail ${i}`,
        createdAt: i * DAY,
        context: { tags: ['topic'] },
      })
    }
    const eight = m.retrieve('Episode concerning subject 3', 8, false).map(c => c.id)
    const four = m.retrieve('Episode concerning subject 3', 4, false).map(c => c.id)
    expect(eight).toHaveLength(8)
    expect(eight.slice(0, 4)).toEqual(four)
  })

  it('is invariant to truncating the pool, i.e. K never enters the score', () => {
    const m = mkMem(NO_GATING, 30 * DAY, { retrievalScoreMode: 'rrf' })
    for (let i = 0; i < 10; i++) {
      m.encode({
        id: `e${i}`,
        content: `Memory ${i} about the colour ${i} and the city ${i * 2}`,
        createdAt: i * DAY,
        context: { tags: [] },
      })
    }
    const a = m.retrieve('colour 3 city 6', 10, false).map(c => c.id)
    const b = m.retrieve('colour 3 city 6', 3, false).map(c => c.id)
    expect(a.slice(0, 3)).toEqual(b)
  })

  it('exposes the rank contributions so a fused ranking stays explicable', () => {
    const m = mkMem(DEFAULT_GATING, 30 * DAY, { retrievalScoreMode: 'rrf' })
    m.encode({ id: 'e0', content: 'Alice visited the Louvre in Paris', createdAt: 0, context: { tags: ['travel'] } })
    m.encode({ id: 'e1', content: 'Bob bought a bicycle in Berlin', createdAt: DAY, context: { tags: ['shopping'] } })
    const top = m.retrieve('Louvre Paris', 2, false)
    expect(top).toHaveLength(2)
    for (const c of top) {
      expect(c.parts.z).toBeDefined()
      expect(c.parts.z!.similarity).toBeGreaterThan(0)
      expect(c.parts.affect).toBe(0)
    }
  })
})

describe('retrieve under `rrf` — an unknown mode degrades to the default', () => {
  it('a snapshot written before \'rrf\' existed rehydrates as \'standardized\'', () => {
    // Defensive: never throw on a persisted config the current code does not
    // know about; fall back to the published default instead.
    const m = mkMem(DEFAULT_GATING, 30 * DAY, { retrievalScoreMode: 'nonsense' as never })
    m.encode({ id: 'e0', content: 'Alice visited the Louvre in Paris', createdAt: 0, context: { tags: [] } })
    const weird = m.retrieve('Louvre', 1, false)
    const sane = mkMem(DEFAULT_GATING, 30 * DAY, { retrievalScoreMode: 'standardized' })
    sane.encode({ id: 'e0', content: 'Alice visited the Louvre in Paris', createdAt: 0, context: { tags: [] } })
    expect(weird.map(c => `${c.id}:${c.score}`)).toEqual(sane.retrieve('Louvre', 1, false).map(c => `${c.id}:${c.score}`))
  })
})
