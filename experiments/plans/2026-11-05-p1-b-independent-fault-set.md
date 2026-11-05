# P1-B: Detection power of the drift and gate matrices on an independently constructed fault set

**Status.** Committed to this repository on its own on 5 November 2026, before the tool's configuration and before any mutant run. It is not registered on an external platform. By the first author's decision of 5 November 2026 it runs on the Mac before the supervisor's review: the tool and its version are the first author's proposal, not a value the supervisor has agreed, and the plan was not sent to the supervisor before the run.
*Last revised: 31 October 2026 (this header line added on 3 November 2026; checked again on 4 November 2026). Code statements checked against commit `97aab7c` of the code repository (the desk check was made at `767e98e`; the files it read are unchanged since).*
*Revisions: 27 October 2026 (the tool is qualified on this solution before use); 31 October 2026 (desk check at `767e98e`, nothing run: the files of the three source areas, the test each matrix runs, how the tool's outcomes are scored and what qualification checks).*

## Study information

**Research question.** How many faults that the authors did not write do the contract-drift matrix and the promotion-gate matrix detect?

**Why.** The paper's mutation scores (0.50 for the drift matrix, 9 of 18 executable mutants; for the gate matrix 0.65 over its 20 mutants and 0.87 over the 15 it can reach) come from hand-written mutants, and closing the gaps they revealed would be regression testing, not a new estimate of detection power.

**Hypotheses.** None. No score is predicted; the study reports what the matrices detect, whatever it is.

## Design plan

**Study type.** Mutation analysis with a general-purpose tool.

**Design.** A general-purpose mutation tool Stryker.NET 5.0.0 (`dotnet-stryker` on NuGet, the newest release on 5 November 2026) generates mutants with its default operators in three source areas: the HTTP boundary and envelope validation, the kernel validation functions, and the promotion service with its gates. The drift matrix is run against mutants of the first two areas; the gate matrix against mutants of the third. *Tool check (2026-10-25): the release notes of Stryker.NET 5.0.0 (2026-09-11) list "Target dotnet 10 runtime"; it has not yet been tried on this solution, which needs the tool downloaded.*

**Source areas (fixed now; files and line counts at `767e98e`).**
1. *HTTP boundary and envelope validation:* `src/Aijade.Server/V9/Boundary.cs`, `src/Aijade.Server/V9/V9Endpoints.cs` and `src/Aijade.Server/V9/V9EventService.cs` (888 lines).
2. *Kernel validation functions:* `src/Aijade.Memory/Kernel/Events.cs` and the schema engine it uses, `src/Aijade.Core/Schema/WireSchema.cs` (403 lines).
3. *Promotion service with its gates:* `src/Aijade.Server/V9/PromotionService.cs`, the integrity anchor `src/Aijade.Memory/V9/ShadowParams.cs`, the evidence gate `src/Aijade.Memory/Development/Vse.cs` and the PGC commit verdict `src/Aijade.Memory/Pgc/PgcGate.cs` (965 lines).

Whole files are mutated, including code that the matrix never executes, such as the other endpoints in `V9Endpoints.cs` and job parsing in `PromotionService.cs`, which the gate matrix bypasses; these mutants are kept and scored as described under Variables. The files are those of the hand-written mutants, except `ServerRuntime.cs` (observation dispatch and the promotion-queue worker, part of none of the three areas) and `BioticMemory.cs` (the in-memory store, which the drift matrix never constructs), with the kernel's schema engine added.

**Matrix tests (fixed now).** The drift matrix is the test `Aijade.Tests.ContractDriftMatrixTests.Matrix_log_equals_the_recorded_baseline_line_by_line`, and the gate matrix the test `Aijade.Tests.PromotionGateMatrixTests.Tampered_candidates_are_refused_without_writes_and_the_control_and_probes_are_promoted`; each tool run selects one of them and no other test. Both need PostgreSQL. Each starts its own server host on a newly created database, so mutants run in parallel share no data. The tool runs on a checkout of this plan's commit to which only the tool's configuration is added, in one commit on a branch of its own, made before the first mutant run and recorded in the results. The files of the three areas, the two tests, the recorded baseline of the drift matrix (`tests/Aijade.Tests/Golden/p1/`) and the test host (`tests/Aijade.Tests/ServerTestHost.cs`) are therefore those of this plan's commit, and later commits, such as the configuration switches of P1-A or the code of Chapter 7, do not enter the mutant set or the tests.

**Tool settings if the tool is Stryker.NET (fixed now).**
- The default mutation level (Standard), with no mutator or method excluded.
- The default coverage analysis (per test) and the default timeouts.
- The VSTest runner. The test project runs under VSTest (`dotnet test`, as in CI) and carries the VSTest adapter, and the tool's test filter does not work with the xUnit v3 runner of Microsoft Testing Platform.
- One run per source project (`Aijade.Server`, `Aijade.Memory`, `Aijade.Core`) and matrix, five runs in all, each listing its files in the tool's `mutate` option. The test project references several projects, so the tool must be told which one to mutate, and its documentation does not mention the solution's `.slnx` format.

The tool cannot mutate constant values, so faults in `const` declarations, such as the topic names in `Events.cs`, are not generated; this is reported as a limit of the mutant set.

## Sampling plan

**Existing data.** None.

**Mutant set.** Every mutant the tool generates in the files above. Exclusion rules, fixed now:
1. Mutants that do not compile are dropped and counted.
2. Mutants the tool reports as timed out, or ignores for a reason of its own, are counted separately.
3. Mutants judged equivalent by hand are excluded only with a written reason per mutant, reported in full.

A mutant is never excluded because the matrix cannot reach it.

**Stopping rule.** One pass over the full mutant set. A pass that does not complete is restarted in full and listed as a deviation; only the first complete pass is reported.

## Variables

**Measured.** Per mutant: the tool's outcome (killed, survived, no coverage, compile error, timeout, ignored); equivalent by hand, with the reason; the operator, file and line.

**Killed (fixed now).** A mutant is killed when the selected matrix test fails, as the tool records it. For the gate matrix, this means a case line turned to FAIL or the test ended in an exception. For the drift matrix, it also includes an assertion log that differs from the recorded baseline without a red line. The hand-written experiments counted a mutant as caught only when at least one assertion line turned red, and excluded a run that ended without a log (no hand-written mutant did). The two criteria therefore differ, and the scores are compared only descriptively.

**Index.** With K killed mutants, S mutants that survived although the matrix executes them, and N mutants that no test of the matrix executes (the tool's "no coverage"), the mutation score per matrix is K / (K + S + N). The score over executed mutants, K / (K + S), is reported alongside. Neither excludes mutants judged unreachable by hand, as the hand-written gate score of 0.87 did. Its nearest counterpart is the score over executed mutants, and the difference in definition is stated with it.

## Analysis plan

**Reporting.** Each matrix's two scores are given with Wilson 95% intervals that treat mutants as units (a description of this mutant set, not a population estimate), overall and by area and file. They are set next to the hand-written scores (0.50 for the drift matrix; 0.65 over all gate mutants and 0.87 over the reachable ones) and not pooled with them. Mutants that survived or were not covered are listed by operator and source location.

**Check of the tool's outcomes (fixed now).** The kernel's schemas are declared in static field initializers (`Events.cs`), which run once when a type is first loaded. Every mutant in a static field initializer that the tool reports as surviving is therefore also applied by hand to a copy of the source, and the matrix test is run on it. Where the two outcomes differ, the hand outcome is used for that mutant, and the number of differences is reported.

**Separation from regression.** Re-running the earlier hand-written mutants after any test change is reported separately as regression testing and does not enter the detection-power result.

**Inference criteria.** None beyond description; a low score is reported as found, and the paper's claims about the matrices are worded on it.

## Other

**First step.** The tool is first run on this solution to confirm that it builds it and discovers and runs its tests. Its initial test run must execute each matrix test, not skip it, with every assertion green. Both tests are skipped when no database is configured, and a skipped test would let every mutant survive. If the tool does not pass these checks, the change of plan is recorded before another tool is chosen; mutants are never selected to favor the known gaps.

**Plan and record.** This plan is committed on its own before the tool's configuration is written. The results record the tool's version and configuration files, this plan's commit and the run's commit (runs set `AIJADE_GIT_COMMIT`), the PostgreSQL version and the machine.

**Resources.** Download of the mutation tool (permission required); local machine, several hours; both matrices need PostgreSQL.

**Deviations.** Listed with date and reason. Known at commit (5 November 2026):
- The draft expected P1-A's configuration switches to come after this plan's commit. They came first (`537a84e`, `de70ae5`), so this plan's commit holds them: 48 added lines in `Boundary.cs`, `V9Endpoints.cs` and `V9EventService.cs`, which take no path while `Aijade:P1aConfiguration` is unset. Mutants on those lines stay in the set under the rules above, and their number and outcomes are also reported in a row of their own, so that the score can be read without them. `Aijade.Memory/Kernel/Events.cs`, `WireSchema.cs`, the promotion files, the two tests and the host are unchanged since `767e98e`.
- The machine is an 8-CPU Mac that is also running other containers, so the tool's concurrency is set low; a mutant that times out because of that load cannot be told apart from one that hangs, and the timeouts are reported as they are.
- 5 November 2026, before any result was kept: the VSTest runner failed the first step. On `Events.cs` the tool found the one selected test and ran it green, then reported that the capture of test coverage had failed, and all 147 mutants tested survived with no test recorded as covering them, including statement removals on paths the matrix executes. xUnit v3 runs tests in a process of its own, which the tool's in-process collector does not reach, so the most likely reading is that no mutant was ever active. That pass is not a result and is not reported as one. The next attempt keeps the tool and its version, and changes the runner to the tool's `MicrosoftTestPlatform` runner, which has no test filter: each matrix therefore gets a test project of its own on the run branch that compiles only that matrix's test file and the host (no source file changes), so each run still selects one test and no other. The first step is repeated with a positive control: if the matrix kills no mutant in `WireSchema.cs`, whose validation it runs on every request, the runner fails too and the change of plan is recorded again.
