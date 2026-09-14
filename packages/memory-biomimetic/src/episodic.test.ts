import type { EpisodicSource } from './episodic'

import { describe, expect, it } from 'vitest'

import { EpisodicGraph } from './episodic'

const SRC_A: EpisodicSource = { id: 's1', trusted: true, contentDigest: 'sha256:aaa' }
const SRC_B_SAME: EpisodicSource = { id: 's2', trusted: false, contentDigest: 'sha256:aaa' }
const SRC_B_DIFF: EpisodicSource = { id: 's2', trusted: false, contentDigest: 'sha256:bbb' }

function graphWithEvents(): EpisodicGraph {
  const g = new EpisodicGraph()
  g.addEvent({ id: 'e1', contentRef: 'ev:1', occurredAt: 100 }, [SRC_A])
  g.addEvent({ id: 'e2', contentRef: 'ev:2', occurredAt: 200 }, [SRC_A])
  g.addEvent({ id: 'e3', contentRef: 'ev:3', occurredAt: 300 }, [SRC_A])
  return g
}

describe('addEvent — §6 无来源不入图', () => {
  it('admits an event carrying at least one source', () => {
    const g = new EpisodicGraph()
    expect(g.addEvent({ id: 'e1', contentRef: 'ev:1', occurredAt: 1 }, [SRC_A])).toEqual({ ok: true })
    expect(g.size).toBe(1)
    expect(g.event('e1')?.contentRef).toBe('ev:1')
  })

  it('rejects a sourceless event and counts the refusal (traceability is measured, not assumed)', () => {
    const g = new EpisodicGraph()
    const r = g.addEvent({ id: 'e1', contentRef: 'ev:1', occurredAt: 1 }, [])
    expect(r.ok).toBe(false)
    if (!r.ok)
      expect(r.reason).toMatch(/source/)
    expect(g.size).toBe(0)
    expect(g.refusals).toBe(1)
  })

  it('rejects a duplicate event id', () => {
    const g = new EpisodicGraph()
    g.addEvent({ id: 'e1', contentRef: 'ev:1', occurredAt: 1 }, [SRC_A])
    const r = g.addEvent({ id: 'e1', contentRef: 'ev:dup', occurredAt: 2 }, [SRC_A])
    expect(r.ok).toBe(false)
    if (!r.ok)
      expect(r.reason).toMatch(/already present/)
    expect(g.size).toBe(1)
  })

  it('reports traceabilityRate 1 once every event carries a source', () => {
    expect(graphWithEvents().traceabilityRate()).toBe(1)
  })
})

describe('observed_in — 佐证与矛盾并存（§10.1）', () => {
  it('keeps multiple agreeing sources (corroboration, not a contradiction)', () => {
    const g = graphWithEvents()
    g.addSource('e1', SRC_B_SAME)
    expect(g.sourcesOf('e1')).toHaveLength(2)
    expect(g.contradictions()).toHaveLength(0)
  })

  it('keeps BOTH conflicting sources and reports the contradiction (no forced single fact)', () => {
    const g = graphWithEvents()
    g.addSource('e1', SRC_B_DIFF)
    const sources = g.sourcesOf('e1')
    expect(sources).toHaveLength(2)
    expect(sources.map(s => s.contentDigest).sort()).toEqual(['sha256:aaa', 'sha256:bbb'])

    const c = g.contradictions()
    expect(c).toHaveLength(1)
    expect(c[0].eventId).toBe('e1')
    expect(c[0].kind).toBe('conflicting_source')
    expect(c[0].sources).toHaveLength(2)
  })

  it('treats a missing digest as unknown, not as a contradiction', () => {
    const g = graphWithEvents()
    g.addSource('e1', { id: 's3', trusted: true })
    expect(g.contradictions()).toHaveLength(0)
  })

  it('rejects attaching a source to an unknown event', () => {
    const g = new EpisodicGraph()
    expect(g.addSource('nope', SRC_A).ok).toBe(false)
  })
})

describe('before/after — 时序自洽且不成环', () => {
  it('accepts a before edge between known events', () => {
    const g = graphWithEvents()
    expect(g.addEdge({ kind: 'before', from: 'e1', to: 'e2', createdAt: 0 }).ok).toBe(true)
  })

  it('rejects the reverse edge that would create a cycle', () => {
    const g = graphWithEvents()
    g.addEdge({ kind: 'before', from: 'e1', to: 'e2', createdAt: 0 })
    const r = g.addEdge({ kind: 'before', from: 'e2', to: 'e1', createdAt: 0 })
    expect(r.ok).toBe(false)
    if (!r.ok)
      expect(r.reason).toMatch(/cycle/)
  })

  it('rejects an indirect cycle (e1→e2→e3→e1)', () => {
    const g = graphWithEvents()
    g.addEdge({ kind: 'before', from: 'e1', to: 'e2', createdAt: 0 })
    g.addEdge({ kind: 'before', from: 'e2', to: 'e3', createdAt: 0 })
    const r = g.addEdge({ kind: 'before', from: 'e3', to: 'e1', createdAt: 0 })
    expect(r.ok).toBe(false)
    if (!r.ok)
      expect(r.reason).toMatch(/cycle/)
  })

  it('rejects a temporal self-loop', () => {
    const g = graphWithEvents()
    const r = g.addEdge({ kind: 'before', from: 'e1', to: 'e1', createdAt: 0 })
    expect(r.ok).toBe(false)
    if (!r.ok)
      expect(r.reason).toMatch(/self-loop/)
  })

  it('rejects an edge from an unknown event', () => {
    const g = graphWithEvents()
    expect(g.addEdge({ kind: 'involves', from: 'ghost', to: 'ent', createdAt: 0 }).ok).toBe(false)
  })

  it('treats "after" as the inverse direction of "before" (a after b ⇒ b before a)', () => {
    const g = graphWithEvents()
    g.addEdge({ kind: 'after', from: 'e2', to: 'e1', createdAt: 0 })
    expect(g.temporalOrder()).toEqual(['e1', 'e2', 'e3'])
  })

  it('produces a deterministic topological order', () => {
    const g = graphWithEvents()
    g.addEdge({ kind: 'before', from: 'e3', to: 'e1', createdAt: 0 })
    g.addEdge({ kind: 'before', from: 'e1', to: 'e2', createdAt: 0 })
    expect(g.temporalOrder()).toEqual(['e3', 'e1', 'e2'])
  })

  it('rejects an unknown edge kind', () => {
    const g = graphWithEvents()
    const bad = { kind: 'maybe_caused', from: 'e1', to: 'e2', createdAt: 0 } as never
    const r = g.addEdge(bad)
    expect(r.ok).toBe(false)
    if (!r.ok)
      expect(r.reason).toMatch(/Unknown episodic edge kind/)
  })
})

describe('caused_candidate / expressed_as / involves', () => {
  it('keeps multiple causal CANDIDATES and does not pick one', () => {
    const g = graphWithEvents()
    g.addEdge({ kind: 'caused_candidate', from: 'e1', to: 'outcome:x', createdAt: 0 })
    g.addEdge({ kind: 'caused_candidate', from: 'e1', to: 'outcome:y', createdAt: 0 })
    expect(g.causalCandidates('e1').sort()).toEqual(['outcome:x', 'outcome:y'])
  })

  it('records embodied expressions (audio / motion / action)', () => {
    const g = graphWithEvents()
    g.addEdge({ kind: 'expressed_as', from: 'e1', to: 'audio:1', createdAt: 0 })
    g.addEdge({ kind: 'expressed_as', from: 'e1', to: 'motion:nod', createdAt: 0 })
    expect(g.expressionsOf('e1').sort()).toEqual(['audio:1', 'motion:nod'])
  })

  it('records involved entities', () => {
    const g = graphWithEvents()
    g.addEdge({ kind: 'involves', from: 'e1', to: 'entity:alice', createdAt: 0 })
    expect(g.entitiesOf('e1')).toEqual(['entity:alice'])
  })

  it('filters edges from an event by kind', () => {
    const g = graphWithEvents()
    g.addEdge({ kind: 'involves', from: 'e1', to: 'entity:alice', createdAt: 0 })
    g.addEdge({ kind: 'caused_candidate', from: 'e1', to: 'outcome:x', createdAt: 0 })
    expect(g.edgesFrom('e1')).toHaveLength(3) // 含入图时的 observed_in
    expect(g.edgesFrom('e1', 'involves')).toHaveLength(1)
    expect(g.edgesFrom('e1', 'expressed_as')).toHaveLength(0)
  })
})

describe('end-to-end: 一段有争议的经历（矛盾并存 + 候选因果）', () => {
  it('preserves disagreeing evidence while still exposing candidate causation and temporal order', () => {
    const g = graphWithEvents()
    // 两个目击者说法不一 —— 都留下，不裁决
    g.addSource('e2', SRC_B_DIFF)
    // 时序与因果候选
    g.addEdge({ kind: 'before', from: 'e1', to: 'e2', createdAt: 0 })
    g.addEdge({ kind: 'before', from: 'e2', to: 'e3', createdAt: 0 })
    g.addEdge({ kind: 'caused_candidate', from: 'e2', to: 'outcome:door_slam', createdAt: 0 })
    g.addEdge({ kind: 'expressed_as', from: 'e2', to: 'motion:flinch', createdAt: 0 })

    // 矛盾被保留而非裁决
    expect(g.sourcesOf('e2')).toHaveLength(2)
    expect(g.contradictions().map(c => c.eventId)).toEqual(['e2'])
    // 结构仍然可用
    expect(g.temporalOrder()).toEqual(['e1', 'e2', 'e3'])
    expect(g.causalCandidates('e2')).toEqual(['outcome:door_slam'])
    expect(g.expressionsOf('e2')).toEqual(['motion:flinch'])
    // §6 与自洽性
    expect(g.traceabilityRate()).toBe(1)
    expect(g.refusals).toBe(0)
  })

  it('does not silently drop a sourceless attempt — it is counted instead', () => {
    const g = new EpisodicGraph()
    g.addEvent({ id: 'ok', contentRef: 'ev:ok', occurredAt: 1 }, [SRC_A])
    g.addEvent({ id: 'bad', contentRef: 'ev:bad', occurredAt: 2 }, [])
    expect(g.size).toBe(1)
    expect(g.refusals).toBe(1)
    expect(g.event('bad')).toBeUndefined()
  })
})
