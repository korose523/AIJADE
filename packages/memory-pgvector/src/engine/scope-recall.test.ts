import type { LongTermMemory } from './types'

import { describe, expect, it } from 'vitest'

import { createHashEmbedder } from './embed'
import { rankLongTerm, reinforcementBoost, timeDecay } from './scope-recall'

const rawEmbedder = createHashEmbedder(128)
const embed = (text: string): number[] => rawEmbedder(text) as number[]

function lt(id: string, scope: string, text: string, over: Partial<LongTermMemory> = {}): LongTermMemory {
  const ts = 1_000_000
  return {
    id,
    tier: 'longterm',
    scope,
    text,
    embedding: embed(text),
    timeRange: { firstSeen: ts, lastSeen: ts },
    salience: 0,
    createdAt: ts,
    sourceIds: [],
    ...over,
  }
}

describe('timeDecay', () => {
  it('returns 1 for age 0', () => {
    expect(timeDecay(0, 0, 1000)).toBe(1)
  })
  it('halves at exactly one half-life', () => {
    expect(timeDecay(0, 1000, 1000)).toBeCloseTo(0.5)
  })
  it('quarters at two half-lives', () => {
    expect(timeDecay(0, 2000, 1000)).toBeCloseTo(0.25)
  })
  it('never exceeds 1 for negative age', () => {
    expect(timeDecay(0, -500, 1000)).toBe(1)
  })
})

describe('reinforcementBoost', () => {
  it('is 1 at salience 0', () => {
    expect(reinforcementBoost(0)).toBe(1)
  })
  it('grows with salience', () => {
    expect(reinforcementBoost(1)).toBeCloseTo(2)
    expect(reinforcementBoost(3)).toBeCloseTo(3)
  })
  it('is capped', () => {
    expect(reinforcementBoost(100)).toBe(4)
  })
})

describe('rankLongTerm', () => {
  const now = 2_000_000
  const half = 1_000_000
  const memories = [
    lt('a', 'game', 'user likes playing minecraft and building redstone'),
    lt('b', 'chat', 'user enjoys cooking pasta with tomato sauce'),
  ]

  it('filters by scope', () => {
    const r = rankLongTerm(embed('minecraft'), memories, { scopes: ['game'], now, halfLifeMs: half })
    expect(r.map(x => x.memory.id)).toEqual(['a'])
  })

  it('returns nothing when no scope matches', () => {
    const r = rankLongTerm(embed('minecraft'), memories, { scopes: ['coding'], now, halfLifeMs: half })
    expect(r).toHaveLength(0)
  })

  it('filters by minSimilarity', () => {
    const r = rankLongTerm(embed('minecraft redstone building'), memories, { now, halfLifeMs: half, minSimilarity: 0.5 })
    expect(r.map(x => x.memory.id)).toEqual(['a'])
  })

  it('ranks the more similar memory first', () => {
    const r = rankLongTerm(embed('minecraft redstone'), memories, { now, halfLifeMs: half })
    expect(r[0].memory.id).toBe('a')
    expect(r[0].similarity!).toBeGreaterThan(r[1].similarity!)
  })

  it('applies time decay (fresher ranks higher)', () => {
    const fresh = lt('f', 'game', 'minecraft redstone', { timeRange: { firstSeen: now, lastSeen: now } })
    const old = lt('o', 'game', 'minecraft redstone', { timeRange: { firstSeen: now - half, lastSeen: now - half } })
    const r = rankLongTerm(embed('minecraft redstone'), [fresh, old], { scopes: ['game'], now, halfLifeMs: half })
    expect(r[0].memory.id).toBe('f')
    expect(r[0].score).toBeGreaterThan(r[1].score)
  })

  it('reinforcement boosts ranking', () => {
    const weak = lt('w', 'game', 'minecraft redstone', { salience: 0 })
    const strong = lt('s', 'game', 'minecraft redstone', { salience: 3 })
    const r = rankLongTerm(embed('minecraft redstone'), [weak, strong], { scopes: ['game'], now, halfLifeMs: half })
    expect(r[0].memory.id).toBe('s')
  })
})
