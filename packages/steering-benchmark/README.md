# @proj-aijade/steering-benchmark

Agent **steering / perturbation-recovery** benchmark harness for AIJADE.

## What it is

A structural evaluation harness that measures how well an agent-under-test
**recovers** from injected faults across task dimensions. It pairs two ideas:

1. **T×P matrix** — task dimensions (`T1/T2/T3`) crossed with perturbation kinds
   (`P1/P2/P3` = `latent` / `transient` / `permanent`).
2. **Degree-preserving randomization** — the configuration-model null
   distribution used as a topology-comparison signal (the "Connectome
   Randomization" angle).

## Methodology provenance (honesty note)

This package borrows its *methodology* from the **MOSAIC** project — a separate
project **derived from AIJADE** — specifically:

- the `T1/T2/T3` task dimensions + `P1/P2/P3` perturbation taxonomy, and
- degree-preserving (edge-shuffle) randomization as a robustness/attribution axis.

All algorithms are **reimplemented here from scratch** (no code copy, no GPL /
copyleft dependency). Reference concepts: graspologic `EdgeSwapper` (degree-
preserving MCMC) and ToolMaze's Perturbation Recovery Rate (PRR) / Recovery Cost
are *methodological citations only* — they are NOT dependencies.

> **Scope boundary.** This is a **structural / behavioral** harness. It does NOT
> contain a neural simulator or any connectome data. The "connectome
> randomization" is reproduced at the graph-topology level only. Wiring real
> fruit-fly connectome data (FlyWire / MaleCNS, CC-BY-NC — **non-commercial**)
> into this harness is a separate, license-gated concern and is intentionally
> left out of this package.

## Reproducibility

Every random draw is seeded (`mulberry32`). A fixed seed yields a bit-exact null
model — consistent with AIJADE's determinism pre-check.

## Usage

```ts
import { applyPerturbation, runSteeringBenchmark } from '@proj-aijade/steering-benchmark'

const result = runSteeringBenchmark({
  referenceTraces: { T1: referenceTrace },
  perturbationKinds: ['latent', 'transient', 'permanent'],
  recover: perturbed => myAgent.recover(perturbed), // the agent's re-plan loop
})
// result.cells -> [{ taskDim, kind, prr, recoveryCost }]
// result.meanPrr -> mean Perturbation Recovery Rate
```

## Scripts

- `pnpm -F @proj-aijade/steering-benchmark selftest` — standalone check (no vitest)
- `pnpm -F @proj-aijade/steering-benchmark test` — vitest suite
