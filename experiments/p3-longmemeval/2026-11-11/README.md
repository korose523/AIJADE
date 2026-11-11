# Frozen LongMemEval eligibility correction and second-corpus product text study

> Current archived status: all 500 histories executed, 246,738 product writes and 2,000 actual request captures; kernel/product numerical reconstructions and AI-assisted figure QA passed. The source-freeze statuses below are retained historical records, not the final execution status. Scientific scope and remaining gates are stated in the completed-execution section.


Plan: [`a7961cf8cde1de659c2272a664d4c936a50484c4`](../../plans/2026-11-11-p3-longmemeval-eligibility-and-product-text.md), pushed before implementation and outcome calculations. Input is the unchanged cleaned LongMemEval_s release pinned by `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`.

The legacy loader used marked-turn presence alone. Official abstention IDs can still contain marked turns: 9 of the 30 `_abs` questions do so. Thus the old 479-marked-question frame includes nine abstention cases. The corrected primary frame is 470 non-abstention cases, not 479. Source annotations are retained; this does not allege an upstream label error. The 21 evidence-free abstentions are retained in complete product execution with null recall denominators. These are input-contract observations, not new retrieval results.

`official/` retains the README, retrieval-metric script and MIT license fetched through the GitHub connector at official source commit `9e0b455f4ef0e2ab8f2e582289761153549043fc`. The official retrieval script filters IDs containing `_abs`. A newer LongMemEval version exists; this fixed cleaned release is used for historical comparability.

The standard adapter now uses `answerable-v2`; existing kernel commands default to the separate `experiments/memory-longmemeval-answerable-v2/` output so they do not overwrite the frozen historical directory; `legacy-marked-v1` reconstructs the previous shapes and timestamps exactly, and `all-questions-v1` retains all 500 histories and source flags. `tools/p3_longmemeval/export_inputs.py` records complete eligibility, hashes, date fallback and session dependence. Expected answers are written separately and are never product query/context input.

`longmemeval-journal` in `tools/Aijade.Experiments` writes fresh sufficient records for every marked case. Both declared frames are aggregated from the same journal. Every numerical metric in the five historical files must reconstruct within 1e-9 before corrected primary results are accepted. Component records preserve the distinction between the historical mean of within-question SD and an additionally labelled pooled SD. Predicted-gating p-values have a predeclared four-contrast Holm family.

`LongMemEvalProductPolicyTests.Complete_second_corpus_text_policy_measurement` is opt-in. It writes all 246,738 nonblank turn occurrences through the real authenticated perception API into fresh owned stores, then captures four actual text-policy completion requests per question (2,000 total). The fixed local SSE reply marks the request boundary, without model inference or answer evaluation. Source positions remain distinct, native PostgreSQL wildcard/tied-time semantics are preserved, and unknown attribution remains bounded. The default provider and production policies are unchanged. The 308 relevant production/config/existing P3 kernel files match the prior LoCoMo study; the administrative tool-module registration and five already-published P2 source changes outside this path are separately disclosed in `production-source-identity.json`.

Run only clean committed binaries, heavy phases serially, through `tools/p3_longmemeval/run_bounded.py` with `DOTNET_PROCESSOR_COUNT=2`. Its 8 CPU-hour/12 wall-hour/3 GiB process-family/512 MiB-file limits, sustained host-memory/swap limits and 24-hour follow-up ceiling implement the plan. Receipt PASS establishes bounded execution, not scientific acceptance. The existing Docker test database is a shared service outside the descendant RSS sum; host available-memory/swap limits remain active. No P2/model retry, embedding, training, external upload, deployment or paid compute is included.

At source freeze, full kernel and product results are **NOT_RUN**. Later results must retain their actual execution source commit, binary identities, complete/unfinished denominators, all adverse/null outcomes and independent aggregation audits. Dense/external-system second-corpus work remains open. Chinese Academy of Sciences journal eligibility, Mac qualification, author approval and submission readiness remain separate unresolved gates.


## Completed execution and numerical acceptance

This section postdates the source-freeze status above. The measurement source remains `9d17f8235508afa1cfba9e6da758f1738adfe8ea`; the later archive adds records and hash-identified audit programs, rather than claiming those programs were in the measurement commit.

All 500 source questions remain in the ledger. The fresh kernel journal has 479 marked cases and the corrected primary frame has 470 non-abstention cases. All five historical numerical families passed the declared 1e-9 reconstruction gate. The product phase made 246,738 real perception-API writes and captured all 2,000 actual outgoing request bodies. It used no live answer/embedding model, and did not test answer quality.

| Fixed text policy | Pool fraction | Complete-prompt fraction L–U | Pool-to-prompt loss L–U | Unknown / truncated primary cases |
|---|---:|---:|---:|---:|
| 6-newest | 0.749433 | 0.054078–0.054078 | 0.695355–0.695355 | 3 / 439 |
| 6-server | 0.749433 | 0.174965–0.177092 | 0.572340–0.574468 | 1 / 432 |
| 60-newest | 0.749433 | 0.054078–0.054078 | 0.695355–0.695355 | 3 / 439 |
| 60-server | 0.749433 | 0.174965–0.177092 | 0.572340–0.574468 | 1 / 432 |

L–U are identification bounds, not confidence intervals. Fractions average the source-marked turn fractions over all 470 primary cases. A partial turn can still contain useful information; complete-turn loss is not measured answer loss. All three prespecified product contrasts and all four predicted-gating contrasts, including adverse and non-identified outcomes, remain in the records.

The 470 primary histories share 3,556 source-session IDs and form one overlap component. This is not an effective-N or user-identity estimate. Case bootstrap/sign-flip results are conditional reweighting sensitivities, not independent-user replication or dependence-robust population inference. All 30 official abstentions remain in execution; the 21 evidence-free cases retain null denominators. Exact-content input diagnostics do not establish semantic annotation completeness.

Layout: `inputs/` contains eligibility, separate answers, session overlap and input-only diagnostics; `execution/` contains bounded receipts, telemetry and program/binary identities; `qualification/` retains actual synthetic requests and the failed/passing development TRX files; `results/` contains the complete kernel/product records; `audit/` retains independent numerical reconstructions and case ledgers; `figures/` retains editable exports, source CSV and AI-assisted QA. `manifest.json` lists every other physical file by size and SHA-256. The raw kernel journal is losslessly gzip-compressed; its uncompressed SHA matches the measurement receipt. Canonical corpus files are not vendored.

Run the stdlib archive/point-estimate check from the repository root:

```sh
python3 experiments/p3-longmemeval/2026-11-11/verify_archive.py
```

The separate `test_archive_rejections.py --out /tmp/aijade-lme-refusals.json` command checks a missing final capture, a changed primary denominator and a contradictory unknown-attribution flag in temporary linked copies; it preserves the source archive and starts no service. Use a new report path on repeats.

For complete numerical reconstruction, use Python with NumPy (the execution records identify exact versions). Run `audit_kernel.py --kernel results/kernel --inputs inputs --out UNIQUE_NEW_OUTPUT` from this directory. From the repository root, run `tools/p3_longmemeval/analyze_product.py --product experiments/p3-longmemeval/2026-11-11/results/product --inputs experiments/p3-longmemeval/2026-11-11/inputs --out UNIQUE_NEW_OUTPUT`. `verify_qualification.py --qualification qualification` checks the eight saved qualification requests. These audits start no database or model service. Preserve existing outputs rather than reusing an old destination.

The existing Docker database is a shared service outside the owned process-family accounting; host-memory/swap limits still applied. This numerical acceptance and AI-assisted visual QA do not establish formal Mac model qualification, independent human adjudication, dense/external-system second-corpus results, evolving Web/QQ behavior, CAS journal eligibility, author approval or submission readiness. No P2 retry, deployment, release, DOI deposition or message sending was performed.

