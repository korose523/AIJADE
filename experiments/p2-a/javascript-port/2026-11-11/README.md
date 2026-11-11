# P2-A JavaScript port

This packet covers the 425 tasks previously classified as direct, including the 52 with a blocking condition in the Python reference preparation. The plans in `experiments/plans/` record the population, comparison rules, Jint transport corrections and four exact arithmetic repair variants. The archive `76f7f26` supplies the accepted typed reference pass and the released source files.

The port builds JavaScript functions from the supported Python source syntax. The individually written ports under `overrides/` implement the same algorithms or more efficient equivalents. `python-semantics.js` provides the source-language operations required by the generated functions. The task-specific contracts cover exact BigInt values, Unicode code points, tuple and dictionary representations, and the decimal string result of HumanEval/83. Host decoding of trusted scalar hexadecimal expectations preserves exact JavaScript bigint comparison. Generation and both verifier templates state the same `solve` binding rule used by the public-task Jint path.

The exact arithmetic variants use separate case identities and expected values derived from the statement checks. Their code lives under `exact-variants/`. `input-lock.json` identifies the input and code inventories for the final Jint replays. The fixed public inputs and outputs are used for development conformance, and author review of statement interpretations remains a separate step before model evaluation.

## Released case replay

| Dataset | Ported tasks | Tasks with full agreement | Planned cases | Cases agreeing |
|---|---:|---:|---:|---:|
| HumanEval+ | 117 | 116 | 83,474 | 82,460 |
| MBPP+ | 308 | 306 | 33,279 | 33,169 |

The frozen replay `fe6df9150c11c4f24db73487472ab40d7cdbf3a0` records 116,753 case identities. The status counts are 115,629 pass, 1,014 unknown, 109 missing reference, 1 mismatch. The port population contains all 425 original direct tasks. The other 117 static-screen tasks are indexed by the input inventory and remain outside this replay.

The Python reference recovery re-executed the three incomplete direct tasks twice. Compression reduced the output files for `HumanEval/15` and `Mbpp/630` within the declared compressed-file limit. Both complete pairs agree and match the earlier prefixes. `Mbpp/255` still reached the RSS monitor in both attempts. Its plus case 85 specifies 1,663,740 combinations of length 77. Only the three base cases have released reference records for this task. The archive stores a single copy of each distinct compressed stream and both process receipts.

The full Jint replay stopped at the CPU limit for `HumanEval/132`. A targeted linear implementation matched all 1,014 released cases under the same limits. A separate check found 30 differences when the statement's subsequence allows skipped characters. The proposed contiguous interpretation and the validated implementation are in `results/clarified-132/`. `Mbpp/739` retains the released replay's exact BigInt disagreement and the separately validated arithmetic repair.

## Statement audit and task dispositions

The [52-task table](results/blocked-tasks.md) and machine-readable `results/blocked-tasks.jsonl` record each prior blocker, representation, observed outcome, statement rule, retained case identity and remaining decision. The statement audit covered 9,113 cases with 8,424 agreeing, 338 outside the declared domain, 193 conflicts, 49 unresolved and 109 missing references. The task dispositions are 46 released ports for author review and 4 local exact variants for author review. `Mbpp/255` and `Mbpp/260` require reference coverage and a statement decision respectively. The latter's released recurrence produces sequence values including composites although the statement asks for primes.

The four exact variants cover 1,048 in-domain cases with 1,048 Jint agreements. They address 138 conflicting released expectations in `HumanEval/99`, `Mbpp/267`, `Mbpp/287` and `Mbpp/739`. They were designed after the observed conflicts. The 425-task replay retains the released values. The literal-example audit across the class records 393 matching examples and 456 agreeing example–case checks. Author review of the interpretations and final task eligibility is pending.

## Reproduction

Use the frozen commit from `results/release/execution.json` for the original replay, and the archived `results/recovery/` for the lossless supplement. `prepare.py --pack PATH --recovery PATH --ports PATH` reconstructs the task and code files. `variants.py` builds the exact cases using the archived `results/semantic/` directory. `input-lock.json` binds both inventories. Build `JintReplay/JintReplay.csproj` with the pinned .NET SDK and use `replay.py --final` with the DLL, runtime, task inventory and port inventory. The commands show their required arguments with `--help`.

Run `python3 verify_archive.py` from this directory to recompute the case and disposition counts and verify the source and artifact identities. `results/release/` contains every case outcome and process receipt. `results/engineering/` retains the development summaries, nonpassing case rows and process outputs. The statements and generated JavaScript are in `results/statements.jsonl` and `results/ports.jsonl.gz`. The released corpus licences and upstream notices accompany the source files in the earlier reference packet. The replay records zero model calls.
