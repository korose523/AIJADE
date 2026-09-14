import type { LayeredMemoryOptions } from './layered-memory'

import { describe, expect, it } from 'vitest'

import { LayeredMemory } from './layered-memory'

/** Build a LayeredMemory with a controllable clock and deterministic compaction. */
function mem(overrides: Partial<LayeredMemoryOptions> = {}) {
  let t = 1_000_000
  const m = new LayeredMemory({
    now: () => t,
    episodicCompactThreshold: 0,
    summarizer: entries => entries.map(e => e.text).join(' | '),
    distiller: text => text.split('|').map(s => s.trim()).filter(Boolean),
    ...overrides,
  })
  return { m, advance: (ms: number) => { t += ms } }
}

describe('ingest & stats', () => {
  it('ingests episodic memories and reports counts', async () => {
    const { m } = mem()
    await m.ingestEpisodic('hello', { scope: 'chat' })
    await m.ingestEpisodic('world', { scope: 'chat' })
    expect(m.stats().episodic).toBe(2)
  })
})

describe('compact (episodic → summary → long-term)', () => {
  it('compacts episodic into a summary and distills long-term facts', async () => {
    const { m } = mem({ episodicCompactThreshold: 3 })
    for (let i = 0; i < 4; i++)
      await m.ingestEpisodic(`msg ${i}`, { scope: 'chat' })

    const summaries = await m.compact()
    expect(summaries).toHaveLength(1)
    expect(m.stats().summaries).toBe(1)
    // default test distiller splits the joined summary on '|' → one fact per message
    expect(m.stats().longTerm).toBe(4)
    expect(m.stats().episodic).toBe(0)
    expect(m.stats().vectorStoreSize).toBe(4)
  })

  it('keeps per-scope episodic isolated', async () => {
    const { m } = mem()
    await m.ingestEpisodic('a', { scope: 'chat' })
    await m.compact('chat')
    await m.ingestEpisodic('b', { scope: 'game' })
    await m.compact('game')
    expect(m.stats().summaries).toBe(2)
    expect(m.stats().longTerm).toBe(2)
  })

  it('merges near-identical long-term facts within a scope', async () => {
    const { m } = mem()
    await m.ingestEpisodic('minecraft redstone', { scope: 'game' })
    await m.compact('game')
    await m.ingestEpisodic('minecraft redstone', { scope: 'game' })
    await m.compact('game')
    expect(m.stats().longTerm).toBe(1)
  })
})

describe('recall', () => {
  it('filters results by scope', async () => {
    const { m } = mem()
    await m.ingestEpisodic('minecraft is fun', { scope: 'game' })
    await m.ingestEpisodic('i like pasta', { scope: 'chat' })
    const res = await m.recall('minecraft', { scopes: ['game'] })
    expect(res.length).toBeGreaterThan(0)
    expect(res.every(r => r.scope === 'game')).toBe(true)
  })

  it('ranks the relevant long-term memory first', async () => {
    const { m } = mem()
    await m.ingestEpisodic('user likes playing minecraft and building redstone contraptions', { scope: 'game' })
    await m.ingestEpisodic('user enjoys cooking pasta with tomato sauce', { scope: 'game' })
    await m.compact('game')
    const res = await m.recall('tell me about minecraft and redstone')
    const lt = res.filter(r => r.tier === 'longterm')
    expect(lt.length).toBe(2)
    expect(lt[0].text).toContain('minecraft')
  })

  it('orders equal-relevance long-terms by recency (time decay)', async () => {
    const { m, advance } = mem({ halfLifeMs: 1_000_000 })
    await m.ingestEpisodic('minecraft redstone', { scope: 'game' })
    await m.compact('game')
    advance(2_000_000) // two half-lives later
    await m.ingestEpisodic('minecraft redstone', { scope: 'chat' })
    await m.compact('chat')

    const res = await m.recall('minecraft redstone', { scopes: ['game', 'chat'], reinforce: false })
    const lt = res.filter(r => r.tier === 'longterm')
    expect(lt).toHaveLength(2)
    expect(lt[0].scope).toBe('chat') // more recent -> higher score
    expect(lt[1].scope).toBe('game')
  })

  it('reinforces long-term memory on recall (salience +1 each call)', async () => {
    const { m } = mem()
    await m.ingestEpisodic('minecraft redstone', { scope: 'game' })
    await m.compact('game')
    expect(m.getLongTerm()[0].salience).toBe(0)

    await m.recall('minecraft redstone', { scopes: ['game'] })
    await m.recall('minecraft redstone', { scopes: ['game'] })
    await m.recall('minecraft redstone', { scopes: ['game'] })
    expect(m.getLongTerm()[0].salience).toBe(3)

    // reinforce:false must not bump salience
    await m.recall('minecraft redstone', { scopes: ['game'], reinforce: false })
    expect(m.getLongTerm()[0].salience).toBe(3)
  })
})

describe('prune', () => {
  it('drops expired episodic memories', async () => {
    const { m, advance } = mem()
    await m.ingestEpisodic('ephemeral', { scope: 'chat', ttlMs: 500 })
    await m.ingestEpisodic('permanent', { scope: 'chat' })
    advance(1000)
    const { prunedEpisodic } = m.prune()
    expect(prunedEpisodic).toBe(1)
    expect(m.stats().episodic).toBe(1)
  })

  it('trims long-term tier to capacity, keeping most salient', async () => {
    const { m } = mem({ longTermCapacity: 2 })
    for (const sc of ['a', 'b', 'c']) {
      await m.ingestEpisodic('unique fact', { scope: sc })
      await m.compact(sc)
    }
    expect(m.stats().longTerm).toBe(3)
    const { prunedLongTerm } = m.prune()
    expect(prunedLongTerm).toBe(1)
    expect(m.stats().longTerm).toBe(2)
  })
})
