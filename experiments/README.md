# Experiments

Every number the papers report is computed from the files in this directory; the paper toolchain (`_工具/facts.py` in
the separate papers repository) reads them directly. Each file is produced by a driver in this repository, listed below;
re-running the driver regenerates it.

The papers are numbered P1, P2 and P3. Run records written before 19 October 2026 (for example the `experiment` field of
`memory/uncertainty.json` and the title of `p1/mutation/mutation-report.md`) still use the earlier labels: P4 for the
retrieval-scoring paper, now P3, and J1 for the Chinese version of P1. Records are kept as they were produced.

`plans/` holds analysis plans committed to this repository before the analyses they describe were implemented or run;
the commit history is their timestamp. They are not registered on an external platform.

| Directory | Paper | Contents | Produced by |
|---|---|---|---|
| `p1/` | P1 | End-to-end main flow (`e2e-main.txt`) and prefer-absence branch (`e2e-negative-fork.txt`); ingestion latency (`ingest-*.json`) and loop latency (`loop-latency.json`) | `tools/Aijade.P1` against a running API + worker |
| `p1/mutation/` | P1 | Mutation experiment on the contract-drift matrix | `tools/Aijade.Mutation` (`mutations.json`) |
| `p1/gate-mutation/` | P1 | Mutation experiment on the promotion-gate matrix | `tools/Aijade.Mutation --catalogue tools/Aijade.Mutation/gate-mutants.json` |
| `p1/admission-checks.json`, `p1/validation-overhead.json` | P1 | Admission checks; strict-validation overhead | `AdmissionChecksTests`, `ValidationOverheadTests` with `AIJADE_EXPERIMENT_DIR=experiments/p1` |
| `p1/identity-a7.json` | P1 | Appendix A.7 positive control of the identity layer | `aijade-experiments identity-a7` |
| `growth-pilot/` | P1 | Mechanism-level pilot of the growth and identity layer | `aijade-experiments growth-pilot` |
| `memory/` | P3 | Weight ablation, score-combination ablation, component scales, K-dependence and retrieval floor, gating interference, salience sources, leakage audit, metric definitions, conversation-clustered intervals of the headline contrasts (`uncertainty.json`), coverage of the 150-candidate pool and the diagnostic over the whole store (`pool-check.json`), delivery with the conflict penalty on and off (`delivery-check.json`), gating contrasts without the penalty (`gating-penalty-off.json`), the follow-up re-analysis on answerable questions with per-evidence recall and the gating × scorer interaction (`answerable-reanalysis.json`, plan `plans/2026-10-22-followup-analyses.md`) (LoCoMo) | `aijade-experiments memory` (or one part: `component-scales`, `k-dependence`, `metric-definitions`); `aijade-experiments memory-uncertainty`, `pool-check`, `delivery-check`, `gating-check`, `answerable-check` |
| `memory-longmemeval/` | P3 | Replication on LongMemEval_s: component diagnosis and gating contrasts (`replication.json`, question-level bootstrap intervals), and the same pool, component-scale, delivery and gating checks as for LoCoMo | `aijade-experiments longmemeval`; `pool-check`, `component-scales`, `delivery-check`, `gating-check` with `--corpus longmemeval` |
| `rq-c/` | P2 | RQ-C runs (`summary.json`, `trials.jsonl`, `candidates.jsonl`), temperature sweep, model-based analysis (`p2-models.json`), sandbox isolation (`<run>/sandbox-isolation.json`), differential testing (`<run>/differential.json`), determinism pre-check and its repeat on the loaded model (`determinism-7b.json`, `determinism-7b-repeat.json`), model weight digests (`model-digests.json`), verifier error rates by environment feedback and by round (`verifier-feedback.json`, plan `plans/2026-10-22-followup-analyses.md`) | `tools/Aijade.Rqc` (`run-redo.sh`, `run-sweep.sh`), `aijade-experiments p2-models`, `aijade-experiments sandbox-isolation`, `aijade-experiments differential --run <dir>`, `aijade-experiments verifier-feedback` |
| `rq-c/family/` | P2 | First attempt at the second-family control (llava-phi3), abandoned at step 5,505 because its verifier ignores the verdict format (`ABANDONED.md`); kept as data | `run-family.sh` |
| `rq-c/family-gpu/` | P2 | Second-family control: llama3.1:8b on the Windows GPU host over Tailscale (Ollama 0.40.0, context 4096), same design as the main run; determinism pre-checks (`determinism-llama3.1-8b*.json`) | `AIJADE_OLLAMA_URL=http://<host>:11434 run-family-gpu.sh llama3.1:8b`, then `finish-family.sh` |
| `rq-c/template-gpu/` | P2 | Prompt-template control (registered before the runs): the main model on the Windows GPU host with verifier prompt A (pre-registered) and B (alternative wording); determinism pre-check `determinism-7b-fixedseed.json` | `AIJADE_OLLAMA_URL=http://<host>:11434 run-template.sh A` (and `B`), then `aijade-experiments p2-models` |
| `rq-c/format-precheck/` | P2 | Verdict-format pre-checks of the candidate replacement models (rule fixed before testing) | `aijade-experiments format-precheck --model M --ollama-base-url U` |

The LoCoMo corpus is third-party data and is not part of the repository; `aijade-experiments memory` reads it from
`$AIJADE_LOCOMO` or `~/.local/share/aijade-data/locomo10.json` and checks its SHA-256 before running; `tools/data/fetch-corpora.sh`
downloads both corpora to the default paths and verifies them.
LongMemEval_s (cleaned release, MIT) is read from `--data`, `$AIJADE_LONGMEMEVAL` or `~/.local/share/aijade-data/longmemeval/longmemeval_s_cleaned.json`, also
checked against its SHA-256.

**RQ-C estimands (2026-10-15).** `summary.json` files written before 2026-10-15 carry, under `diagnostics.hallucinationRate` /
`missRate`, the predictive values P(unusable | self-pass) / P(usable | self-fail). The estimands of P2 §3.2 condition on the
oracle instead; `RqcAnalysis` and `aijade-experiments p2-models` now report both families under their own names
(`falseDiscoveryRate`, `falseOmissionRate`), and the papers read the recomputed `p2-models.json`.
