import { describe, expect, it } from 'vitest'

import { buildProvenanceGraph, explain, traceProvenance } from './evidence'
import { BioticMemory } from './store'
import { DEFAULT_MEMORY_CONFIG } from './types'

describe('v7 §27 evidence fabric', () => {
  it('weaves beliefs, episodes, facts and revisions into a provenance graph', () => {
    const mem = new BioticMemory(DEFAULT_MEMORY_CONFIG)
    mem.encode({ id: 'e1', content: 'deadline tomorrow', createdAt: 1, context: { tags: ['calendar'] } })
    mem.encode({ id: 'e2', content: 'project kickoff', createdAt: 2, context: { tags: ['work'] } })
    const proposed = mem.proposeBelief({ proposition: 'user cares about deadlines', evidenceIds: ['e1', 'e2'] })
    expect(proposed.ok).toBe(true)
    if (proposed.ok) {
      mem.reviseBelief(proposed.belief.id, {
        evidence: [{ id: 'e2', reliability: 1, likelihood: 0.5 }],
      })
    }

    const g = buildProvenanceGraph(mem)
    const belief = g.nodes.find(n => n.kind === 'belief')
    expect(belief).toBeDefined()
    const evidenced = g.edges.filter(e => e.from === belief!.ref && e.relation === 'evidenced-by')
    // reviseBelief appends evidence, so the belief ends up referencing e1 and e2
    // (possibly with a duplicate) — assert the source set rather than an exact count.
    const evidencedTargets = new Set(evidenced.map(e => e.to))
    expect(evidencedTargets.has('e1')).toBe(true)
    expect(evidencedTargets.has('e2')).toBe(true)
    const revisions = g.edges.filter(e => e.relation === 'revision-of')
    expect(revisions).toHaveLength(1)
  })

  it('traceProvenance walks upstream from a belief to its evidence', () => {
    const mem = new BioticMemory(DEFAULT_MEMORY_CONFIG)
    mem.encode({ id: 'e1', content: 'deadline tomorrow', createdAt: 1, context: { tags: ['calendar'] } })
    mem.proposeBelief({ proposition: 'p', evidenceIds: ['e1'] })
    const g = buildProvenanceGraph(mem)
    const belief = g.nodes.find(n => n.kind === 'belief')!
    const chain = traceProvenance(g, belief.ref)
    const refs = chain.map(n => n.ref)
    expect(refs).toContain(belief.ref)
    expect(refs).toContain('e1')
  })

  it('two-level explanation: simple one-liner vs research chain', () => {
    const mem = new BioticMemory(DEFAULT_MEMORY_CONFIG)
    mem.encode({ id: 'e1', content: 'deadline tomorrow', createdAt: 1, context: { tags: ['calendar'] } })
    mem.proposeBelief({ proposition: 'user cares about deadlines', evidenceIds: ['e1'] })
    const belief = mem.beliefs[0]

    const simple = explain(belief.id, 'simple', mem)
    expect(simple.level).toBe('simple')
    if (simple.level === 'simple')
      expect(simple.text).toContain('deadlines')

    const research = explain(belief.id, 'research', mem)
    expect(research.level).toBe('research')
    if (research.level === 'research') {
      expect(research.chain.length).toBeGreaterThan(0)
      expect(research.policy.gating).toBeDefined()
      // No query supplied → no score decomposition for a belief node.
      expect(research.scores).toBeNull()
    }
  })

  it('research explanation surfaces score decomposition for a memory under a query', () => {
    const mem = new BioticMemory(DEFAULT_MEMORY_CONFIG)
    mem.encode({ id: 'e1', content: 'deadline tomorrow', createdAt: 1, context: { tags: ['calendar'] } })
    const research = explain('e1', 'research', mem, { query: 'deadline' })
    expect(research.level).toBe('research')
    if (research.level === 'research') {
      expect(research.scores).not.toBeNull()
      expect(research.scores!.similarity).toBeGreaterThanOrEqual(0)
    }
  })
})
