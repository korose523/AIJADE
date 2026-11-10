# P3-E: current shared-runtime full-corpus measurement

Both final conditions cover all 10 LoCoMo conversations and all 1,986 questions. The primary set is 1,540 answerable questions; four list no evidence, leaving 1,536 recall denominators. Nine questions with unlocated evidence remain in that primary denominator. All-question and located-evidence views are separate in `summary.json`.

Plan `d1527e01d19c7e5524a0afa3f003d741a9d131a6` was committed and pushed separately before instrumentation. The author explicitly authorized this Mac run; no supervisor receipt, approval or external preregistration is inferred. Product base: `d9dcf6bdc928f822e7a2fc3bf4e2cb00a36ebade`. Final execution: `c6c48eb3ac531a8d798c675809740cb15fd8013d`, rebuilt at that clean commit; test/client/server informational versions and actual binary hashes are retained. Source hashes for 875 existing product, configuration and historical experiment files remain unchanged.

| Primary measure (conversation mean; 95% bootstrap interval) | Text | Embedding |
|---|---|---|
| Observed complete-item recall | 0.118183 [0.089561, 0.144012] | 0.247552 [0.186023, 0.311994] |
| Candidate-pool to observed-prompt loss | 0.474979 [0.448793, 0.500073] | 0.748675 [0.685437, 0.808867] |
| Planned to observed additional loss | 0.000000 [0.000000, 0.000000] | 0.000000 [0.000000, 0.000000] |

All 3,972 requests were captured, with zero failed turns, response-recomputation mismatches, unexplained blocks or ambiguous sources. Text has 1,973 complete memory blocks and 13 absent blocks; embedding has 1,986 complete blocks. No block was truncated on this corpus. Observed gold counts match the corresponding historical snapshots question by question; this is descriptive agreement, not general prompt equivalence or a causal architecture effect. The 10,000 conversation-bootstrap resamples use seed 20261110, distinct from the historical seed.

The local embedding path made 2,081 actual upstream HTTP requests for 7,868 inputs. The verification script called no model. NumPy 2.3.5 independently recomputes the numerical formula on the same captured vectors: all 1,986 server searches match, with no floating rank ties. These are not independent participants, annotations or answer evaluations.

## Scope and provenance

The entry is the shared runtime with only memory enabled, empty history per question, synchronous API ingestion and no question write-back into memory. A local completion-response stand-in returns fixed text; no chat model generates or judges an answer. It is not a full Web/QQ-host, life-context, multi-turn, proactive or reminder evaluation. The one-hour harness deadline differs from the ordinary product timeout. No P2 regeneration, policy comparison or Chapter 7 acceptance is implied.

`attempt-02/` contains the final raw reports, durable row journals, per-conversation stores, actual upstream embedding responses, commands and test results. Large JSON files are losslessly compressed; `receipt.json` records both compressed hashes and original-source hashes. `summary.json`, `vector-crosscheck.json`, `capture-negative-checks.json` and `numeric-consistency.json` separate statistical summaries, numerical verification, rejection checks and manuscript facts. Actual binary identities are in `execution-identity-attempt-02.json`. The embedding model is the existing local `nomic-embed-text`, digest `0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f`, with no task prefix; service/runtime observations are retained.

## Interrupted attempt retained

`attempt-01/` retains the complete text pass and 915 embedding questions, including 28 memory HTTP 500 responses. A reused recording handler was disposed by named-client factory cleanup. Rotation alone passed; delayed cleanup reproduced `ObjectDisposedException` (`diagnostics/`). The repair creates a fresh transport handler per factory creation and shares only recording state, preserving the default product handler lifetime. After repair both conditions ran again from fresh stores. No rows were merged. Qualification at the exact execution commit passed 15 tests with one full-corpus opt-in skip; the two final full-corpus tests each passed separately. GitHub CI for execution commit c6c48eb passed 573 tests, skipped 20; 38 browser cases were not enabled.

## Reproduction and refusal checks

Use the original corpus file matching SHA-256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`. The scripts read either plain or compressed captures. Do not overwrite the archived outputs; choose new paths.

```sh
python3 experiments/p3-e/2026-11-10-shared-runtime/summarize.py experiments/p3-e/2026-11-10-shared-runtime/attempt-02 --corpus /path/to/locomo10.json --out /tmp/p3e-recomputed.json
uv run --with numpy==2.3.5 python experiments/p3-e/2026-11-10-shared-runtime/verify_embeddings.py experiments/p3-e/2026-11-10-shared-runtime/attempt-02/embedding --out /tmp/p3e-vectors.json
python3 tools/audit_advisor_evidence.py --out /tmp/p3e-audit.json --current-product-receipt experiments/p3-e/2026-11-10-shared-runtime/receipt.json --require-current-version
```

The capture validator rejects missing rows, duplicate question keys and a corrupted system hash in both report and journal. Unknown attribution is not observed zero: its population accounting uses conservative bounds. The receipt auditor checks artifact/source/coverage consistency and retains the historical-v1 refusal when the new receipt is not selected. It does not independently attest to execution or approve scientific conclusions.

## Dataset attribution

LoCoMo: Adyasha Maharana, Dong-Ho Lee, Sergey Tulyakov, Mohit Bansal, Francesco Barbieri and Yuwei Fang, Evaluating Very Long-Term Conversational Memory of LLM Agents (ACL 2024), https://github.com/snap-research/locomo . Corpus-derived text in stores, prompts and transport records retains the upstream CC BY-NC 4.0 terms, copied in `LOCOMO-LICENSE.txt`; it is not relicensed as product source code. Changes are format projections and measured request/response records. No model files or third-party images are bundled. Procedural-workflow attribution is in the fixed plan.
