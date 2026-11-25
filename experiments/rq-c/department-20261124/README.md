# P2-R on the department computer, 24 November 2026: status and read-only check

Written 25 November 2026. The prospective record is [`DEPARTMENT-EARLY-START-20261124.md`](../DEPARTMENT-EARLY-START-20261124.md) (589bc0f).
Group A used Ollama 0.40.0, group B (exploratory) 0.40.16. The groups are reported separately and never pooled. No number
enters Chapter 5 or the P2 manuscript; whether the runs can be used is for the supervisor to decide.

- **First attempts** (archives 291ef69c…, 45d81cc8…): `INCOMPLETE_DEPARTMENT_EVIDENCE`, no regeneration. The open-sampling
  control failed in both, and GPU error events fell inside both windows (one in A, two in B).
- **Second attempts** (archives 6f7d000c…, 4b85864b…): `QUALIFICATION_EVIDENCE_COMPLETE`, `REGENERATION_EVIDENCE_COMPLETE`.
  On the Mac, `--audit-bundle` gives `CAPTURED_REPEATS_MATCH` for both, every file bound by the four phase receipts matches,
  and the files in `analysis/` were reproduced from the archives.

`analysis/` holds the two-layer reports (12), first divergences (9) and the summaries of A and B. `A-archive` and `B-archive`
compare with the archived runs, `B-local` with the host-2 run of 19 November, `host2-version` the archive with that run.

## Reading

- On programs that occur in both runs the execution oracle never conflicts. The comparisons overlap, so their counts are
  not independent samples.
- The verifier's verdict can differ on an identical program. In group B the second-family verifier failed one usable
  math-fib program 21 times and passed it 5 times; the archive has 1 and 105. All 21 belong to one task, and the
  task-bootstrap interval of the false-omission rate is [0, 1], so no difference is established.
- The Wilson intervals in the summaries treat skills as independent; the task-clustered intervals are the ones to read.

## Deviations

1. Group A ran eight days before the approved start; group B before the supervisor's decision.
2. The oldest retained log record names another computer (stopping rule 3); the author chose the pinned-anchor patch of
   host 2, recorded and pushed before any run.
3. A discarded warm-up request was added to the open-sampling control after its failure. The qualification outputs of
   the two attempts are identical (A: 15 of 15 starts; B: 14 of 15, the other inside a GPU-error window).
4. The retry record required a passing exclusivity check and a separate port; there is no passing receipt, and the
   default port was used.
5. The operator confirmation before regeneration was typed by a wrapper (B) or skipped by a continuation script (A).
6. Source commits 9f67b1b, 204af3a and fddf9a1 and the second-attempt approval receipts are still on the department
   computer. **The full source of the run is therefore not public yet.**
7. Windows 10 and Ubuntu 26.04 instead of Windows 11 and 24.04, NAT networking, and a display driver updated that morning.

Raw archives stay private because their log captures name the host and hold event XML.
The exploratory re-scoring of the plan has not been applied to these runs.
