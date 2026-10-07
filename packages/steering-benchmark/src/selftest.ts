// Standalone self-test (no vitest needed). Run: tsx src/selftest.ts
// Verifies the core algorithms behave correctly and deterministically.

import type { BehaviorTrace } from './perturbation'
import type { Graph } from './randomization'

import { runSteeringBenchmark } from './harness'
import { applyPerturbation } from './perturbation'
import {
  degreePreservingNull,
  directedEdgeSwapMCMC,
  edgeSwapMCMC,

  mulberry32,
} from './randomization'
import { recoveryCost } from './recovery'

let failures = 0
function assert(cond: boolean, msg: string): void {
  if (!cond) {
    failures++
    console.error('FAIL:', msg)
  }
  else {
    console.log('ok  :', msg)
  }
}

// 1. Degree preservation (undirected)
const g: Graph = {
  nodes: ['a', 'b', 'c', 'd', 'e'],
  edges: [['a', 'b'], ['a', 'c'], ['b', 'c'], ['c', 'd'], ['d', 'e'], ['e', 'a']],
}
const deg = (graph: Graph, n: string) => graph.edges.filter(e => e[0] === n || e[1] === n).length
const g2 = edgeSwapMCMC(g, 20, mulberry32(42))
let preserved = g2.edges.length === g.edges.length
for (const n of g.nodes) {
  if (deg(g, n) !== deg(g2, n))
    preserved = false
}
assert(preserved, 'undirected degree sequence preserved after 20 swaps')

// 2. Directed degree preservation
const dg: Graph = {
  nodes: ['a', 'b', 'c', 'd'],
  edges: [['a', 'b'], ['a', 'c'], ['b', 'c'], ['c', 'd'], ['d', 'a']],
}
const outDeg = (graph: Graph, n: string) => graph.edges.filter(e => e[0] === n).length
const inDeg = (graph: Graph, n: string) => graph.edges.filter(e => e[1] === n).length
const dg2 = directedEdgeSwapMCMC(dg, 10, mulberry32(7))
let dPreserved = dg2.edges.length === dg.edges.length
for (const n of dg.nodes) {
  if (outDeg(dg, n) !== outDeg(dg2, n) || inDeg(dg, n) !== inDeg(dg2, n))
    dPreserved = false
}
assert(dPreserved, 'directed in/out degree sequences preserved after 10 swaps')

// 3. degreePreservingNull is deterministic for a fixed seed
const n1 = degreePreservingNull(g, 20, 99)
const n2 = degreePreservingNull(g, 20, 99)
assert(JSON.stringify(n1.edges) === JSON.stringify(n2.edges), 'degreePreservingNull deterministic for fixed seed')

// 4. Perturbation correctness
const ref: BehaviorTrace = {
  id: 't1',
  steps: Array.from({ length: 8 }, (_, i) => ({ t: i, action: `a${i}`, ok: true })),
}
const latent = applyPerturbation(ref, 'latent', { atIndex: 2 })
assert(latent.steps[2].ok === false && latent.steps[3].ok === true, 'latent drops exactly one step')
const permanent = applyPerturbation(ref, 'permanent', { atIndex: 2 })
assert(permanent.steps.filter(s => !s.ok).length === 6, 'permanent drops all steps from atIndex')
const transient = applyPerturbation(ref, 'transient', { atIndex: 2, transientWindow: 3 })
assert(transient.steps.filter(s => !s.ok).length === 3, 'transient drops a 3-step window')

// 5. Recovery metrics: a perfect agent restores everything; a no-op agent restores nothing
const perfect = (p: BehaviorTrace): BehaviorTrace => ({ ...p, steps: p.steps.map(s => ({ ...s, ok: true })) })
const noop = (p: BehaviorTrace): BehaviorTrace => p
const prrPerfect = runSteeringBenchmark({
  referenceTraces: { T1: ref },
  perturbationKinds: ['latent', 'transient', 'permanent'],
  recover: perfect,
})
assert(Math.abs(prrPerfect.meanPrr - 1) < 1e-9, 'perfect agent => mean PRR = 1')
const prrNoop = runSteeringBenchmark({
  referenceTraces: { T1: ref },
  perturbationKinds: ['permanent'],
  recover: noop,
  atIndex: 2,
})
assert(prrNoop.meanPrr === 0, 'no-op agent => PRR = 0 for permanent')
assert(recoveryCost(ref, permanent, perfect(permanent)) === 0, 'recoveryCost 0 when perfectly recovered')
assert(recoveryCost(ref, permanent, noop(permanent)) === 6, 'recoveryCost = 6 for permanent with no-op recovery')

console.log(failures === 0 ? '\nALL SELFTESTS PASSED' : `\n${failures} SELFTEST(S) FAILED`)
if (failures > 0)
  process.exit(1)
