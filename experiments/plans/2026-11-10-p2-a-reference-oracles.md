# P2-A reference execution and serialization preparation

Date: 10 November 2026. Execution requested by the author's instruction to continue the Mac project and manuscript work. This is a separate preparation extension after the completed P3 configured comparisons. The previous P2-A stages 0/1 and their results are known. This plan is committed and pushed on its own before its implementation; it is not externally registered and does not imply supervisor receipt or approval.

## Question and boundary

Which public benchmark tasks that were statically screened for the existing JavaScript oracle actually yield complete, repeatable and representable reference outputs, and what remains unresolved before a JavaScript port or model experiment? Produce an auditable expected-output bank and failure ledger, rather than model/verifier error rates. This is preparation after the translation/data check, not the generation pilot, precision design or P2-A main run. No model is called, no task is assigned to a main-study set, and no HumanEval/MBPP candidate is generated or judged.

The existing P2-R-Mac draft's long hardware qualification and supervisor-confirmed acceptance standard remain independent. This bounded Python reference exercise neither qualifies the Mac for the formal P2 regeneration nor establishes that historical host errors had no effect. Original P2 labels and manuscript facts remain unchanged.

## Inputs and provenance fixed before execution

- HumanEval+ v0.1.10: 164 tasks, 1,570 base inputs and 122,683 extended inputs; compressed SHA-256 `272720b90ac375502c8ed23cd791c2a93dfb22a911641a494da74a426c09f101`.
- MBPP+ v0.2.0: 378 tasks, 1,174 base inputs and 39,841 extended inputs; compressed SHA-256 `af43697e8791c4c149bdfd6b489d8b5412507551ac20e28a439f650b8225db63`.
- The unchanged stage-0 compatibility ledger `experiments/p2-a/evalplus-compatibility.json` supplies the original four classes; stage-1 `multiple-check.json` remains a separate statement/translation audit.
- Official EvalPlus commit `26d6d00bb1fd0fa37f39c99d5290da67891d1c5e`, the version already used by the static screen: preserve the MBPP input deserializer, evaluator/ground-truth source, special-oracle definitions, licenses and source hashes. Use its MBPP deserialization function, including tuple/complex conversions; do not treat raw JSON arguments as the complete Python input semantics. No network download occurs inside a reference worker.
- Reuse the installed CPython 3.12 environment and record the exact interpreter/version. Code/runtime/input identities are frozen before the corpus exercise. Previously tracked runtime, configuration and research evidence, and all 10,613 existing manuscript facts, are protected by a before-run hash inventory.

## Execution and run order

Attempt all 542 tasks, including statically incompatible ones, in two fresh-process passes. Pass 1 is HumanEval then MBPP, numeric task-ID order. Pass 2 reverses the whole task order. These are repeatability checks on fixed public tasks, not independent samples or a population experiment.

For each task, combine the published prompt and canonical solution. Execute base and extended partitions in separate fresh namespaces, as in the upstream ground-truth path. Preserve input order and deserialize a fresh copy of each partition; do not overwrite corpus inputs. Call the declared entry point directly. Within a partition retain the reference function's ordinary state across its calls. Native base assertions/check functions execute in a third fresh namespace and are reported separately from the expected-output loop. An assertion pass establishes agreement with those assertions, not independent semantic truth or coverage of the task description.

Each case record identifies the task, partition, index, original serialized input, restored typed input, typed reference output or exception, and portability flags. Types retain distinctions among bool, int, float, list, tuple, set/frozenset, dict keys, complex and None. Use explicit representations for nonfinite floats, integers outside JavaScript's exact range, and unsupported values; never coerce these into successful JSON-null observations. Preserve all raw rows and all failed/partial attempts. Only a declared tuple-to-array representation is proposed for a later JavaScript port; no claim that the task has been ported follows from serialization alone.

Report native base-assertion outcomes, observed output types and input/output representability alongside the old static class. Flag flat float outputs requiring the upstream tolerance, known task-specific/set/not-None comparisons, and exceptions. Do not silently use exact equality where the official evaluator has another rule. Keep a task blocked if its comparator or type behavior needs an adapter, even if a canonical run succeeds.

## Isolation, limits and qualification

Use one reference process at a time on this 16-GiB Intel Mac. Canonical code runs under a macOS filesystem/network restriction profile, with an empty service-credential environment, read access only to required interpreter/runtime, the worker/upstream source and its supplied input, no network and no writes outside its designated task output. Record the actual command, profile hash and limits. Report the restriction's tested scope without claiming a general security certification.

Before corpus execution, qualification fixtures must show: ordinary reference success; original MBPP type restoration; null/bool and safe-integer distinctions; native base-assertion failure kept separate; cross-case argument mutation/state handled as declared; network and unrelated-file access denied; a nonterminating reference stopped and its partial output retained; missing/duplicate rows and wrong input hashes rejected. Use artificial fixtures only, without inspecting model outputs.

Limits are fixed prospectively: 15 CPU seconds and 30 wall seconds per task process; 512 MiB data-segment resource setting where supported, with a separately reported 1-GiB RSS monitoring stop (sampling is not a hard memory guarantee); 64 MiB output-file limit per task, 64 open-file limit and no core dump. Unsupported OS controls remain unknown rather than being called enforced. A task timeout/error does not stop later tasks. Stop the whole exercise at 45 wall minutes, or on an unexplained environment/isolation failure, and mark remaining tasks NOT_RUN. Do not extend limits after seeing which tasks fail. A pure infrastructure repair requires a dated deviation, fresh complete affected pass, and retained earlier outputs; no merging of favorable partial rows.

## Analysis and acceptance

For every dataset, old class and task, report attempted/completed cases, base/extended coverage, reference exceptions, native assertion results, observed types, unsafe values, repeat agreement and unresolved reasons. Compare semantic records across passes excluding duration/PID fields. Unsupported outputs are not declared value-equal merely because their type labels match. No inferential p-values or test-case confidence intervals are appropriate for this finite preparation ledger.

A preparation-ready task must have all declared inputs observed in both passes, no reference exception, passing native assertions, repeatable representable outputs, and no unresolved comparator requirement; report these criteria separately. This is a mechanical preparation status, not a final eligibility decision, independent human review, proof of task correctness or a completed JavaScript port. All blocked tasks remain in the ledger. Do not revise the stage-0 classification or turn missing/timeout results into negative task outcomes.

Re-analyze the compressed public copies and verify row/count/input/semantic hashes. Reproduce the primary summaries in a separate validator, including rejection cases. Keep raw expected outputs outside model prompts and outside the original SkillBench fixtures; model-facing task statements and secret oracle expectations remain separate in any future runner. Default runtime and archived study code are unchanged.

Archive code, upstream provenance/licenses, qualification, both pass records, every failure, limits, summary and a hash receipt under `experiments/p2-a/reference-oracles/2026-11-10/`. Update P2 English/Chinese sources and Chapter 5/plans/availability with only the measured preparation result and remaining gates. Publish necessary code/evidence to GitHub; preserve the private manuscript worktree's earlier changes. No professor message or journal submission is authorized by this plan.

## Software acknowledgement

Planning and resource interpretation reuse the experimental-design and get-available-resources guidance from Scientific Agent Skills. Its primary reference was verified earlier on 10 November 2026: Kassis, Agarwal, He, Patel and Brueckner, *Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents* (2026), https://doi.org/10.48550/arXiv.2609.00065 . This acknowledges workflow guidance; it is not evidence for the library's efficacy. Interpretation and manuscript drafting remain AI-assisted.
