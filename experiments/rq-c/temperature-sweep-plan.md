# RQ-C temperature sweep (exploratory) — plan fixed before running

Written 2026-10-12T12:08:18Z, before any of the runs below started (the first launch failed to connect because the model server was not running; no run produced data).

**Status: exploratory sensitivity analysis, not part of the pre-registration** (which fixes greedy decoding, T = 0). P2
lists "a temperature sweep" as an open sensitivity analysis; this answers it on the second (.NET) implementation, whose
analysis and sandbox are shown to match the original (experiments/replication/cross-implementation.json).

- Model: qwen2.5-coder:7b-instruct (the main-result model), Ollama 0.35.1, local CPU.
- All design parameters as pre-registered: 30 trials, 5 rounds, 12 tasks, seed 42, prune threshold 0.5, min calls 3.
- Runs, in this order: T = 0 (replication of the archived main result on the second implementation), T = 0.4, T = 0.8.
  Each with the warm-up request and --save-candidates.
- Read-outs (the three conclusions of §6.2–§6.4/§6.6): (1) the sv×ef interaction (estimate, Holm-adjusted p),
  (2) the environment-feedback McNemar test (Holm-adjusted p), (3) self-assessment calibration (missRate,
  hallucinationRate). Also: step-level agreement of the T = 0 run with the archived main result.
- Every run is reported, whatever it shows. No other temperatures, models or settings will be added after seeing results
  without being reported as a further deviation.

## Amendment (2026-10-12T12:30:34Z) — model changed for run time, before any result was looked at

The 7B runs proved far slower on this CPU-only host than planned: about 30–40 s per request, so one 7 200-step run
(≈ 5 000 requests) would take roughly two days and the sweep about a week. The partial T = 0 run (62 steps logged) was
stopped and deleted unread. The sweep is therefore run with **qwen2.5-coder:1.5b** (the second-model control, about
80 minutes per run on the second implementation):

- T = 0.4 and T = 0.8, with every other setting as above; the T = 0 reference is the existing 1.5B re-run on the second
  implementation (experiments/rq-c/rq-c-s42-ollama-t30-r5, already reported in §6.7).
- Read-outs unchanged. Known limitation, stated before running: at T = 0 the 1.5B self-verifier never passes, so
  read-out (3) can only show whether sampling changes that collapse; it cannot say anything about the 7B model.
- A 7B sweep is not run; this is reported as a limitation.

## Amendment 2 (2026-10-13, before any result of the sweep had been computed or inspected)

The T = 0.4 run stopped at step 6105 of 7200: one request exceeded HttpClient's default client-wide timeout of 100 s, which
the second implementation had left in place under the per-request `--timeout-ms 600000` (a bug, now fixed: the client-wide
timeout is disabled and the per-request one governs). No summary had been written, so no result had been seen. The run was
resumed with the new `--resume-from` option: the 3,290 generations and 2,505 self-verification replies recorded in the
interrupted run's candidates.jsonl were replayed in call order — the runner checks every replayed step against the record
and stops on any divergence — and the live model took over from step 6105. The interrupted artifacts are kept under
`sweep-1.5b/interrupted/`. The resumed run reports the replay in its summary (`resumed`) and as a deviation note.
