# P2-R exploratory oracle replay intake

The exploratory analysis keeps the recorded trial path and the original verifier decisions. It reports three label sets side by side. `asRun` uses the recorded execution. `entry` allows the historical lexical-entry fallback, and `entryAndTest` additionally excludes the pinned ambiguous camel-case case. A replay pass can add evidence of usability while a recorded pass remains a pass. Task counts, the distinct-candidate rule and the 10,000 task bootstrap draws follow the original analysis.

## Check the retained reference

```sh
python3 -B experiments/rq-c/rescore_department_oracle.py archive-self-check \
  --out "$P2_ORACLE_ARCHIVE_CHECK"
```

This checks the 44-task, 228-case bench and the exact historical oracle implementation. The three archived populations contain 69, 57 and 49 distinct task/code pairs. The reporter reconstructs the historical aggregate tables from retained promotion classes and their recorded baseline agreement. The original audit supplies aggregate failure witnesses. For platform rounding, the absolute tolerance is `1e-12` for interpolated BCa endpoints and the relative tolerance is `1e-12` for the clustered McNemar p-value. All other values and table structure match exactly. This archive check records zero candidate executions.

## Prepare intake after a completed department phase

The complete regeneration directory and an independently reviewed SHA-256 of its `phase-result.json` are required. Prepare the manifest in the project workspace.

```sh
python3 -B experiments/rq-c/rescore_department_oracle.py manifest \
  --regeneration-bundle "$P2_REGENERATION_DIR" \
  --phase-receipt-sha256 "$P2_REVIEWED_REGENERATION_SHA" \
  --out "$P2_ORACLE_MANIFEST"
```

The output binds all three accepted groups, the source and runner, and the three input files per group. It includes each task's timeout and ordered case indices, the one case exclusion, and each distinct program's task and code digest. Program identities hash the exact extracted UTF-8 code. The raw programs stay in their capture files.

## Derive a transcript from reviewed observations

Supply the recorded output of a separately approved evaluator as `aijade.p2-r.department-oracle-observations.v1`. Copy the manifest's `binding`, inner `manifestSha256`, and whole-file `manifestFileSha256`. Set `evidenceScope` to `OPERATOR_REVIEWED_EXTERNAL_REPLAY` for reviewed external evidence. Supply all three `groups` with their exact `captureFilesSha256` and complete `programs` lists. Each program identifies `taskId` and `codeSha256` from the manifest.

A `CAPTURED` program supplies independent observations for `asRun`, `entry` and `entryAndTest`. Each variant uses `status` and `cases`. For `CASE_RESULTS`, record each executed case as `{"caseIndex": 3, "result": "PASS"}` using the original case indices in the selected variant's order. The possible observations are `PASS`, `FAIL` and `TIMEOUT`. A timeout must be the final observed case, and earlier cases remain in the record. With no timeout, the complete retained case list is required. A `NO_CALLABLE` or `SETUP_ERROR` variant has an empty `cases` list. A `SKIPPED_ARCHIVE_HOST_FACILITY` program carries only its identity and status and requires the exact historical lexical disposition. The historical summary's partial failure list cannot establish the original index of a timed-out case.

The separately reviewed `aijade.p2-r.department-oracle-evaluator-receipt.v1` receipt binds the scope, phase and rule `binding`, both manifest digests, `observationsFileSha256`, `referenceReplayEngineSha256` and each group's capture hashes and `programCount`. Its `evaluatorIdentity` supplies `artifactSha256`, `runtimeSha256`, `invocationContractSha256` and `environmentSha256`. Review those identities and their evidence independently before pinning the receipt. The intake verifies the pinned file and its bindings. The review establishes who produced the observations and how the evaluator was operated.

```sh
python3 -B experiments/rq-c/rescore_department_oracle.py produce \
  --regeneration-bundle "$P2_REGENERATION_DIR" \
  --phase-receipt-sha256 "$P2_REVIEWED_REGENERATION_SHA" \
  --replay-manifest "$P2_ORACLE_MANIFEST" \
  --replay-manifest-sha256 "$P2_REVIEWED_ORACLE_MANIFEST_FILE_SHA" \
  --observations "$P2_REVIEWED_ORACLE_OBSERVATIONS" \
  --observations-sha256 "$P2_REVIEWED_ORACLE_OBSERVATIONS_SHA" \
  --evaluator-receipt "$P2_REVIEWED_ORACLE_EVALUATOR_RECEIPT" \
  --evaluator-receipt-sha256 "$P2_REVIEWED_ORACLE_EVALUATOR_RECEIPT_SHA" \
  --out "$P2_REVIEWED_ORACLE_TRANSCRIPT"
```

The producer writes `aijade.p2-r.department-oracle-replay-transcript.v2` with an `outcome` and the ordered `failedCaseIndices` for each variant. Its terminal outcomes are `PASSED`, `FAILED_CASES`, `NO_CALLABLE`, `SETUP_ERROR` and `TIMEOUT`. A timeout includes the observed `timedOutCaseIndex`. The transcript contains program digests and records the independent evidence identities.

## Score after transcript review

```sh
python3 -B experiments/rq-c/rescore_department_oracle.py score \
  --regeneration-bundle "$P2_REGENERATION_DIR" \
  --phase-receipt-sha256 "$P2_REVIEWED_REGENERATION_SHA" \
  --replay-manifest "$P2_ORACLE_MANIFEST" \
  --replay-manifest-sha256 "$P2_REVIEWED_ORACLE_MANIFEST_FILE_SHA" \
  --observations "$P2_REVIEWED_ORACLE_OBSERVATIONS" \
  --observations-sha256 "$P2_REVIEWED_ORACLE_OBSERVATIONS_SHA" \
  --replay-transcript "$P2_REVIEWED_ORACLE_TRANSCRIPT" \
  --replay-transcript-sha256 "$P2_REVIEWED_ORACLE_TRANSCRIPT_SHA" \
  --evaluator-receipt "$P2_REVIEWED_ORACLE_EVALUATOR_RECEIPT" \
  --evaluator-receipt-sha256 "$P2_REVIEWED_ORACLE_EVALUATOR_RECEIPT_SHA" \
  --out "$P2_ORACLE_SCORE_REPORT"
```

The scorer verifies the independently supplied file digests, re-derives the transcript and requires an exact byte match. It rejects mismatched evidence, missing or duplicate programs, invalid case positions and baseline replay disagreement on a judged skill. It counts baseline disagreements on unjudged skills separately. Both commands require AIJADE-local input and output files.

Offline controls use `SYNTHETIC_FIXTURE` evidence and explicitly set `--evidence-mode synthetic` on both commands. The default external mode refuses those files. Synthetic scores carry the scope `SYNTHETIC_REPLAY_TRANSCRIPT_SCORED`. These commands derive and score records with zero candidate executions. A department run or external candidate replay requires separate execution approval.
