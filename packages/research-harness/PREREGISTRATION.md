# Pre-registration — RQ-C 2×2 experiment

This file is the **registered protocol** for the RQ-C self-verification × env-feedback
2×2 experiment. It exists to close the **selective-inference blocker (B3)**: the
experimental design is fixed *before* looking at outcomes, so the `envFeedback`
effect is estimated on a protocol that was not chosen to make an effect appear.

The single source of truth for these numbers at runtime is the `PREREGISTRATION`
constant in `src/harness.ts`. The CLI and the harness both read their defaults from
it, so code and documentation can never drift apart. `runExperiment` validates the
actual run parameters against this constant and emits a `console.info` warning (and
records `preregistrationDeviation` in the result) whenever a run deviates.

## Fixed design parameters

| Parameter        | Value | Why it is fixed, not tuned                                  |
|------------------|-------|-------------------------------------------------------------|
| `trials`         | 30    | Independent replications per condition (power target).      |
| `rounds`         | 5     | See note below — must exceed `pruneMinCalls`.               |
| `nTasks`         | 12    | Distinct tasks sampled per trial (blocked across conditions). |
| `pruneThreshold` | 0.5   | Precision cutoff for pruning a repeatedly-failing skill.   |
| `pruneMinCalls`  | 3     | Min calls before a skill may be pruned (NOT a tuning knob). |
| `seed`           | 42    | Master seed; per-condition / trial / task seeds derived deterministically. |

## Why `rounds = 5` and not `3`

With `pruneMinCalls = 3` the auto-retire can only fire once a skill has accumulated
`>= 3` calls, so a failing skill is first *eligible* for pruning in round 3. To give
the regeneration a chance to *help* before the run ends we need `rounds > minCalls`,
hence **5**. A 3-round design would let pruning fire only on the last round, leaving
no room for the regenerated candidate to improve precision.

## Analysis unit (B1)

The valid analysis unit is the **skill**, not the execution. Each skill is collapsed
to one binary outcome (success iff `successCount / callCount >= 0.5`) and every
proportion inference is tested at the skill level. The old execution-level chi-square
is retained as `chiSquareExecutionLevel` but is **diagnostic-only** (pseudo-replication).

## Design (B4)

Tasks are sampled **once per trial**, indexed only by the trial number, and the same
task set is reused by all four conditions. `condSeed`/`trialSeed` derive from the
master seed without mixing the condition index into task sampling, so the four
conditions are balanced on task difficulty — making the McNemar pairing valid.

## Inference plan

- **Primary**: skill-level 2×2 chi-square, `envFeedback` (rows) × outcome (cols).
- **Paired**: McNemar test, `envFeedback` ON vs OFF, skills paired by `(trial, task)`.
- **Interaction**: 2×2 factorial log-odds interaction (selfVerification × envFeedback)
  — the headline effect. (This is **not** a difference-in-differences: there is no
  pre/post time dimension.)
- **Multiplicity**: Holm step-down over the primary family (10 inferences: 6 pairwise
  condition contrasts + the factorial interaction + the two main-effect axis tests +
  McNemar), with the two axis tests serving as the omnibus before pairwise contrasts
  are read.
- **Effect sizes**: odds ratio, risk difference, Cramér's V, Cohen's h.
- **Power**: declared via `minDetectableEffectProportion` / `powerForEffectProportion`
  at the achieved skill-per-cell count; the design resolves effects of roughly
  `>= 10pp` at the registered scale.
