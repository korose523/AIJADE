import type { RawScoreRow } from './retrieval'
import type { MemoryConfig } from './types'

import { describe, expect, it } from 'vitest'

import { LexicalDistiller } from './consolidation'
import { collapseDuplicateContent, scoreCandidate, scoreCandidatesStandardized } from './retrieval'
import { BioticMemory } from './store'
import { DEFAULT_GATING, DEFAULT_MEMORY_CONFIG, DEFAULT_RETRIEVAL_WEIGHTS, NO_GATING } from './types'

const W = DEFAULT_RETRIEVAL_WEIGHTS
const DAY = 86_400_000

function mkMem(
  gating: MemoryConfig['gating'],
  now: number,
  override: Partial<MemoryConfig> = {},
): BioticMemory {
  return new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, gating, ...override }, now)
}

function row(over: Partial<RawScoreRow> = {}): RawScoreRow {
  return { similarity: 0, strengthRaw: 0, recency: 0, context: 0, affect: 0, ...over }
}

describe('the weights were not touched — this fix is about scale, not tuning', () => {
  it('pins the original weight values, bit for bit', () => {
    // Pinned on purpose. The published claim is "the defect was in the component
    // scales, not in the weight values"; if anyone tunes a weight to make a
    // number look better, that claim silently becomes false and this fails.
    expect(W).toEqual({ similarity: 1, strength: 0.6, recency: 0.3, context: 0.4, affect: 0.25 })
  })
})

describe('scoreCandidate — legacy additive mode, kept for reproducibility', () => {
  it('is the raw weighted sum of the saturated components', () => {
    const { score, parts } = scoreCandidate(0.2, 3, 0.5, 0.25, 0, W)
    expect(parts.strength).toBeCloseTo(0.75, 10)
    expect(parts.context).toBeCloseTo(0.25, 10)
    expect(score).toBeCloseTo(
      W.similarity * 0.2 + W.strength * 0.75 + W.recency * 0.5 + W.context * 0.25,
      10,
    )
  })
})

describe('scoreCandidatesStandardized — z-scores the components, not the weights', () => {
  it('z-scores each component across the pool and applies the unchanged weights', () => {
    // Only similarity varies: [1, 2] -> mean 1.5, population sd 0.5 -> [-1, +1].
    // Every other column has zero variance and must contribute exactly 0.
    const out = scoreCandidatesStandardized([
      row({ similarity: 1 }),
      row({ similarity: 2 }),
    ], W)

    expect(out).toHaveLength(2)
    expect(out[0].z.similarity).toBeCloseTo(-1, 10)
    expect(out[1].z.similarity).toBeCloseTo(1, 10)
    expect(out[0].z.strength).toBe(0)
    expect(out[0].z.recency).toBe(0)
    expect(out[0].z.context).toBe(0)
    // -1·w and +1·w, shifted so the pool minimum is exactly 0.
    expect(out[0].score).toBeCloseTo(0, 10)
    expect(out[1].score).toBeCloseTo(2 * W.similarity, 10)
  })

  it('exposes the raw values alongside the z-scores so a retrieval stays explicable', () => {
    const out = scoreCandidatesStandardized([row({ similarity: 0.4, strengthRaw: 3 })], W)
    expect(out[0].rawParts.strength).toBeCloseTo(0.75, 10)
    expect(out[0].rawParts.similarity).toBe(0.4)
    expect(out[0].rawParts.affect).toBe(0)
  })

  it('never yields NaN or Infinity when a component has zero variance', () => {
    // "every candidate is equally recent" is not evidence about relevance; it
    // must contribute 0, not silently become a 0/0 tie-break.
    const rows = Array.from({ length: 5 }, () =>
      row({ similarity: 0.3, strengthRaw: 1, recency: 0.5, context: 0.2 }))
    for (const s of scoreCandidatesStandardized(rows, W)) {
      expect(Number.isFinite(s.score)).toBe(true)
      expect(s.score).toBe(0)
      expect(s.z).toEqual({ similarity: 0, strength: 0, recency: 0, context: 0 })
    }
  })

  it('returns non-negative scores — the noise and conflict stages are multiplicative', () => {
    const rows = [
      row({ similarity: 0.4 }),
      row({ similarity: 0.05 }),
      row({ similarity: 0.2 }),
      row({ similarity: 0.01 }),
    ]
    const out = scoreCandidatesStandardized(rows, W)
    for (const s of out)
      expect(s.score).toBeGreaterThanOrEqual(0)
    // The shift is chosen so the minimum lands exactly on 0.
    expect(Math.min(...out.map(s => s.score))).toBe(0)
  })

  it('is invariant to an affine rescaling of a single component', () => {
    // The property the raw sum lacked: multiplying one cue's units by 7 must not
    // re-weight the model.
    const rows = [row({ similarity: 0.1 }), row({ similarity: 0.2 }), row({ similarity: 0.42 })]
    const scaled = rows.map(r => row({ ...r, similarity: r.similarity * 7 + 3 }))
    const a = scoreCandidatesStandardized(rows, W).map(s => s.score)
    const b = scoreCandidatesStandardized(scaled, W).map(s => s.score)
    for (let i = 0; i < a.length; i++)
      expect(b[i]).toBeCloseTo(a[i], 8)
  })

  it('handles an empty pool', () => {
    expect(scoreCandidatesStandardized([], W)).toEqual([])
  })
})

describe('collapseDuplicateContent', () => {
  it('keeps the episode over its derived fact and records what it absorbed', () => {
    const { kept, absorbed } = collapseDuplicateContent([
      { kind: 'fact', id: 'fact_e1', content: 'Alice moved to Berlin', createdAt: 0 },
      { kind: 'episode', id: 'e1', content: 'Alice   moved to\nBerlin', createdAt: 0 },
    ])
    expect(kept.map(k => k.id)).toEqual(['e1'])
    expect(absorbed.get('e1')).toEqual(['fact_e1'])
  })

  it('leaves genuinely distinct content alone', () => {
    const { kept, absorbed } = collapseDuplicateContent([
      { kind: 'episode', id: 'a', content: 'one', createdAt: 0 },
      { kind: 'episode', id: 'b', content: 'two', createdAt: 1 },
    ])
    expect(kept.map(k => k.id)).toEqual(['a', 'b'])
    expect(absorbed.size).toBe(0)
  })
})

describe('retrieve — K-independence', () => {
  it('retrieve(q, 8) begins with exactly retrieve(q, 4)', () => {
    // Without this, recall@1/2/4/8 are not prefixes of one another and cannot be
    // compared — which was silently true before the fix (the R-conflict rerank
    // head used to be `topK`).
    const m = mkMem(DEFAULT_GATING, 30 * DAY)
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
})

describe('retrieve — content deduplication', () => {
  it('drops the byte-identical fact copy so one piece of evidence occupies one rank', async () => {
    const m = mkMem(NO_GATING, 30 * DAY)
    for (let i = 0; i < 9; i++) {
      m.encode({ id: `filler${i}`, content: `Unrelated filler sentence number ${i}`, createdAt: i * DAY, context: { tags: [] } })
    }
    m.encode({ id: 'gold', content: 'Alice visited the Louvre museum in Paris', createdAt: 9 * DAY, context: { tags: [] } })
    await m.consolidate(new LexicalDistiller())

    // Sanity: consolidation really did mint the verbatim duplicate.
    expect(m.facts.some(f => f.id === 'fact_gold')).toBe(true)

    const res = m.retrieve('Louvre museum Paris', 5, false)
    const ids = res.map(c => c.id)
    expect(ids).toContain('gold')
    expect(ids).not.toContain('fact_gold')
    expect(res.find(c => c.id === 'gold')!.parts.deduplicatedIds).toEqual(['fact_gold'])
  })

  it('dedupeByContent: false restores the old two-ranks-per-evidence behaviour', async () => {
    const m = mkMem(NO_GATING, 30 * DAY, { dedupeByContent: false })
    for (let i = 0; i < 9; i++) {
      m.encode({ id: `filler${i}`, content: `Unrelated filler sentence number ${i}`, createdAt: i * DAY, context: { tags: [] } })
    }
    m.encode({ id: 'gold', content: 'Alice visited the Louvre museum in Paris', createdAt: 9 * DAY, context: { tags: [] } })
    await m.consolidate(new LexicalDistiller())
    const ids = m.retrieve('Louvre museum Paris', 20, false).map(c => c.id)
    expect(ids).toContain('gold')
    expect(ids).toContain('fact_gold')
  })
})

describe('retrieve — the corrected default ranks by relevance, not by recency', () => {
  // One old but on-topic memory, ten recent but unrelated ones. This is the
  // situation the LoCoMo corpus is full of, and the sign of the difference is
  // the whole finding.
  const QUERY = 'Louvre museum Paris'
  function build(mode: MemoryConfig['retrievalScoreMode']): BioticMemory {
    const m = mkMem(NO_GATING, 30 * DAY, { retrievalScoreMode: mode })
    m.encode({
      id: 'relevant',
      // Deliberately long. On a real corpus the query is a short question and the
      // memory is a long utterance, so the sparse TF-IDF cosine lands around
      // 0.05–0.2 — well below the ~0.3–0.6 that the recency and strength terms
      // supply on their own. A short on-topic sentence would score too high and
      // hide the effect.
      content: 'Alice recounted that she had visited the Louvre museum in Paris last summer together with her sister, and that they had then spent a long and pleasant afternoon walking slowly through the galleries looking at paintings and sculptures from many different countries and centuries, which she said she had enjoyed very much indeed',
      createdAt: 0,
      context: { tags: [] },
    })
    const decoys = [
      'Bob bought a new bicycle',
      'Carol cooked pasta for dinner',
      'Dave fixed the leaking tap',
      'Erin painted the kitchen wall',
      'Frank washed his car',
      'Grace planted tomatoes',
      'Heidi tuned her guitar',
      'Ivan read a novel',
      'Judy booked a flight',
      'Karl sold his old sofa',
    ]
    decoys.forEach((content, i) => {
      m.encode({ id: `d${i}`, content, createdAt: 30 * DAY, context: { tags: [] } })
    })
    return m
  }

  function rankOf(m: BioticMemory): number {
    return m.retrieve(QUERY, 11, false).findIndex(c => c.id === 'relevant')
  }

  it('standardized mode puts the relevant-but-old memory first', () => {
    expect(rankOf(build('standardized'))).toBe(0)
  })

  it('additive mode ranks at least one recent irrelevant memory above it', () => {
    const additive = rankOf(build('additive'))
    const standardized = rankOf(build('standardized'))
    expect(additive).toBeGreaterThan(standardized)
  })
})
