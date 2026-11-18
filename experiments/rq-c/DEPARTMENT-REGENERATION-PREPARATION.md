# P2-R department-server preparation

The 18 November department-server plan is awaiting a supervisor reply, account access, GPU allocation and error-log visibility. The worklist is an offline derivative of that draft and the original public P2-R protocol. It verifies the nine pinned archive files and the three 7,200-row populations before emitting a command list. It does not contact the department server or start a process.

## Offline commands

Run from the AIJADE source checkout.

```sh
python3 -B experiments/rq-c/prepare_department_regeneration.py
python3 -B -m unittest discover -s experiments/rq-c -p test_prepare_department_regeneration.py -v
```

The output has five independent qualification slots for each of the Llama 3.1 8B, Qwen 7B template A, and Qwen 7B template B configurations. Each slot has five trials, four cells, five rounds and 12 task positions per round, for 1,200 rows. The same output enumerates two separately recorded open-sampling controls and three future 7,200-row regenerations. The explicit command arguments preserve the runner seed, context, output cap, timeout, strict verdict behavior and output separation. Paths and server addresses are unresolved tokens. The stored source summaries say `gitHash: unknown`. The current runner source and the future frozen build have their own identities.

## Capture after authorization

Bind the confirmed plan and the actual runner build to a new execution bundle. Keep the time window, hardware, driver, OS, service, GPU allocation and model identities in the host evidence. Export system and GPU errors immediately before and after the planned window from the same sources, including query and visibility records. A missing error log or inadequate time coverage must remain visible in the investigation.

The worklist's `argvTemplate` values are argument arrays for review. Keep the approved endpoint, actual executable and arguments in the private execution evidence. Use an empty output directory for each qualification slot. Record model unload evidence before each launch and the runner output, retaining any interruption. The historical wrappers implement retries and resumption, so they are inappropriate for the five fresh qualification launches. Do not reuse a completed output directory as evidence of a new launch.

Each qualification bundle supplied to the reader includes:

- `runner-identity.json` with schema `aijade.p2-r.runner-identity.v1`, the emitted worklist SHA-256, full source commit and SHA-256 of the frozen runner DLL. Field names are `worklistSha256`, `sourceCommit` and `runnerSha256`.
- `launch-receipt.json` beside each slot's actual run directory and its `runner.log` and `model-unload.log`. Its schema is `aijade.p2-r.qualification-launch.v1`. Record `group`, `index`, `worklistSha256`, `sourceCommit`, `runnerSha256`, `exitCode`, an independently assigned `launchId`, and zoned `unloadRecordedAt`, `startedAt` and `finishedAt`. The `fileSha256` object binds `trials.jsonl`, `candidates.jsonl`, `summary.json` from the run directory and both logs.
- The actual two Substrate JSON control exports, at the paths in the worklist, with their logs and runtime evidence retained alongside. The reader independently recounts distinct recorded output hashes and reports the discrimination outcome.

Retain the canonical JSON emitted by a particular preparer version. To review a captured bundle offline, invoke the same version.

```sh
python3 -B experiments/rq-c/prepare_department_regeneration.py --audit-bundle /path/to/copied-bundle
```

The reader checks the planned slot population, metadata and artifact binding. It compares each group's later captures with its own first capture, point by point, and records the first divergence without reprinting candidate or verifier text. Distinct operator-recorded launch IDs, nonoverlapping intervals, the warm-up marker and matching summary fields are evidence checks. They do not authenticate the underlying server operations. In particular, the unload log's hash attests the retained bytes. The actual unload, log coverage, hardware condition, and adviser confirmation still require review.

`CAPTURED_REPEATS_MATCH` describes the repeat comparison only. Control discrimination is a separate field. The audit exits 1 if either the recorded repeats differ or the positive control fails to discriminate, and exits 2 for incomplete evidence. `CAPTURED_REPEATS_DIFFER` reports a bound difference, and `INCOMPLETE_RECORD` identifies missing or invalid capture evidence. Review the complete evidence and obtain any further decision required by the plan before a regeneration. The full-run comparator is `regen_compare_v2.py`. Statistical and exploratory oracle re-tallies follow it. The current `oracle_audit.py` reads the archived directories and is not a future-bundle analysis interface.
