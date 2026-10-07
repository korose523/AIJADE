import type { BehaviorTrace } from './perturbation'
import type { Graph } from './randomization'

import { describe, expect, it } from 'vitest'

import { applyPerturbation } from './perturbation'
import { edgeSwapMCMC, mulberry32 } from './randomization'
import { perturbationRecoveryRate } from './recovery'

describe('steering-benchmark', () => {
  it('preserves undirected degree sequence', () => {
    const g: Graph = {
      nodes: ['a', 'b', 'c', 'd', 'e'],
      edges: [['a', 'b'], ['a', 'c'], ['b', 'c'], ['c', 'd'], ['d', 'e'], ['e', 'a']],
    }
    const r = edgeSwapMCMC(g, 20, mulberry32(42))
    const deg = (n: string) => g.edges.filter(e => e[0] === n || e[1] === n).length
    const deg2 = (n: string) => r.edges.filter(e => e[0] === n || e[1] === n).length
    for (const n of g.nodes) expect(deg(n)).toBe(deg2(n))
  })

  it('recovery rate is 1 for a perfect agent', () => {
    const ref: BehaviorTrace = {
      id: 't',
      steps: Array.from({ length: 5 }, (_, i) => ({ t: i, action: `a${i}`, ok: true })),
    }
    const p = applyPerturbation(ref, 'permanent', { atIndex: 1 })
    const perfect = (x: BehaviorTrace) => ({ ...x, steps: x.steps.map(s => ({ ...s, ok: true })) })
    expect(perturbationRecoveryRate(ref, p, perfect(p))).toBe(1)
  })

  it('latent perturbation breaks exactly one step', () => {
    const ref: BehaviorTrace = {
      id: 't',
      steps: Array.from({ length: 5 }, (_, i) => ({ t: i, action: `a${i}`, ok: true })),
    }
    const l = applyPerturbation(ref, 'latent', { atIndex: 2 })
    expect(l.steps.filter(s => !s.ok).length).toBe(1)
  })
})
