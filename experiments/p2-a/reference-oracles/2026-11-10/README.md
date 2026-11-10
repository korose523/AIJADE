# P2-A public-reference preparation

The separately pushed [plan](../../../plans/2026-11-10-p2-a-reference-oracles.md), commit `c97638dec08db3a74d5ac6bd105f8ba5f7e5194c`, fixes all 542 tasks and two fresh-process passes before implementation. The directory date identifies that plan; execution timestamps record the actual run, including the local date crossing into 11 November. No model, verifier, generation pilot or main study runs here.

The corpus hashes retain HumanEval+ v0.1.10 (164 tasks; 124,253 base/extended inputs) and MBPP+ v0.2.0 (378 tasks; 41,015 inputs). `inputs/` contains the unchanged compressed releases; `upstream/` retains required official sources and notices. The input deserializer is compiled from its pinned function AST without running the upstream module's downloader/import initialization. Reference calls use the upstream per-call deepcopy and per-partition namespaces; returned values are retained through each partition before serialization so an aliased return object has the same final value as in the upstream helper.

Records preserve original serialized arguments, restored Python types, reference values/exceptions, comparator requirements and native base-assertion results. Unsafe integers, nonfinite floats, nonstring dict keys, sets, complex values and unsupported objects are not silently replaced by null. Unsupported type labels are not evidence of value agreement. Native assertions and reference outcomes are distinct checks. A mechanical preparation status does not certify the task description, finish a JavaScript port, choose a study task set or estimate model/verifier error rates.

`worker.py` runs only through the Mac controller's restriction profile, without service credentials or network. Artificial checks include unrelated file reads/writes and network denial, timeout retention, original type restoration, argument isolation, partition state, return-object aliasing, native assertion separation and malformed/missing input rejection. Startup initially failed before any corpus/reference record; the corrected profile permits the filesystem root directory as a literal path, not its subtree. Original failures and the correction remain in `engineering/`. This is a tested restriction boundary, not a security certification or formal Mac hardware qualification.

Execution is explicit and refuses a dirty source tree or an existing output directory:

```sh
python3 run.py --execute --qualification engineering/qualification-08/qualification.json --out /path/to/new-private-output
python3 analyze.py /path/to/new-private-output --out /path/to/summary.json
python3 verify.py /path/to/new-private-output --summary /path/to/summary.json --out /path/to/validation.json
python3 export_bank.py /path/to/new-private-output --summary /path/to/summary.json --out /path/to/new-bank
python3 -m unittest -v test_reference.py
```

The controller allows one process at a time, 15 CPU/30 wall seconds and 64 MiB output per task, with separate memory settings/monitoring and a 45-minute total limit. Every failed or partial task remains in the ledger. Analyses run no canonical program or model. The proposed bank exports statements and oracle expectations separately; it is outside the product runtime and original SkillBench fixtures. Model-facing prompts must not load the oracle file in a later study.

## Complete fixed-budget execution on 11 November

The accepted complete rerun used frozen code `1263f708d4ed3fbbca722662c2f36171763d2bb4`, native CPython 3.12.14 and the original limits. Its 1,084 task-process attempts took 359.52 seconds. Both passes attempted every task; the second reverses the full task order. The ledger contains 330,042 case rows across the two passes, with 247 missing inputs per pass retained as unknown.

| Dataset | Tasks | Complete in both passes | Previous static direct class | Prepared within that direct class |
|---|---:|---:|---:|---:|
| HumanEval+ | 164 | 162 | 117 | 103 |
| MBPP+ | 378 | 375 | 308 | 270 |

Of 537 tasks complete in both passes, 533 have comparable typed values and equal semantic records; four have unsupported values, so repeat comparison remains unknown. No unequal comparable complete task was observed. No reference exception appears in the recorded prefixes; this says nothing about missing calls. One native assertion block, `Mbpp/120`, failed with `NameError: math is not defined`: the released assertion uses `math.isclose` while this study's separate fresh namespace has no `math` import. This is a test-environment setup limitation, not evidence of an incorrect canonical function. The task remains blocked under the fixed preparation rule.

The same five tasks were incomplete in both accepted passes: `HumanEval/15`, `HumanEval/130` and `Mbpp/630` reached the 64-MiB output-file limit; `Mbpp/255` was stopped by sampled RSS monitoring; `Mbpp/599` ended with the CPU-limit signal. Their exact stdout bytes, stderr, profiles and process receipts are retained under `failures/attempt-02/`. Limits were not raised. Missing results do not become failing task/model outcomes.

The six mechanical criteria are met by 409 tasks across all old classes, but the proposed bank deliberately takes only the 373 that also belonged to the old static direct class (103 HumanEval+, 270 MBPP+). Its 107,640 pass-1 input/expected pairs live in `bank/oracle-only.jsonl.gz`, separately from the original Python statements in `bank/statements-only.json.gz`. The other 52 old-direct tasks remain blocked by incomplete execution, value representability or unresolved comparison rules; criteria overlap. This bank is not a JavaScript port, a final study task selection or an independent semantic oracle. Translation, comparison adapters, semantic audit, device qualification, model pilots and P2 primary regeneration remain open.

## Rejected first attempt and reproducibility

The entire first attempt (`c2400e4`) is retained under `runs/attempt-01/` and excluded from every accepted summary and bank row. Strict input checking found that recursive JSON key sorting changed a released dictionary's insertion order (`HumanEval/22`, plus input 20). No summary or bank was accepted from that attempt. The separately pushed [amendment](../../../plans/2026-11-11-p2-a-reference-input-order.md), commit `9c755f0`, precedes the order-preserving repair and a new complete pair of passes. Both attempts' bounded failures remain visible. The new artificial order fixture brings the final pre-execution qualification to 17 passing checks; portable semantic checks pass 11/11.

`receipt.json` binds the accepted execution, excluded attempt, source and corpus hashes, all public artifacts and the unchanged 1,192 protected runtime/configuration/research files. `independent-validation.json` recomputes readiness and counts separately. To audit the archived compressed copy without executing canonical functions or a model, run:

```sh
python3 audit.py --out /path/to/audit-result.json
```

Use `--expected-summary-sha` to require a caller-held summary identity; mismatches are rejected. The audit also checks both plans' ancestry, the frozen measuring code, lossless incomplete stdout and strict full public-copy reanalysis. Its consistency result is separate from scientific acceptance. The original 10,613 manuscript facts remain unchanged; new preparation facts use their own namespace.
