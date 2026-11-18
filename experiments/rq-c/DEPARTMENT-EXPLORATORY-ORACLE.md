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

The observed outcomes come from a separately approved, positively identified replay producer. The transcript envelope uses schema `aijade.p2-r.department-oracle-replay-transcript.v1`, copies the manifest's `binding`, carries `manifestSha256` and `reviewedEvaluatorReceiptSha256`, and supplies all three `groups`. Each group copies its `captureFilesSha256` and has a `programs` list. The operator reviews the evaluator evidence and independently pins the finished transcript. The reporter verifies the supplied evaluator receipt's bytes against its digest inside that pinned transcript. The operator's review establishes the receipt's authority.

Each program row identifies `taskId` and `codeSha256`. A `CAPTURED` row supplies each of `asRun`, `entry` and `entryAndTest`. Each result has an `outcome` and ordered `failedCaseIndices`, with indices from the original task case order. Outcomes are `PASSED`, `FAILED_CASES`, `NO_CALLABLE`, `SETUP_ERROR` and `TIMEOUT`. A timeout adds `timedOutCaseIndex` and retains any failures before that case. `SKIPPED_ARCHIVE_HOST_FACILITY` is reserved for the pre-existing lexical disposition and carries only the program identity and status.

```sh
python3 -B experiments/rq-c/rescore_department_oracle.py score \
  --regeneration-bundle "$P2_REGENERATION_DIR" \
  --phase-receipt-sha256 "$P2_REVIEWED_REGENERATION_SHA" \
  --replay-transcript "$P2_REVIEWED_ORACLE_TRANSCRIPT" \
  --replay-transcript-sha256 "$P2_REVIEWED_ORACLE_TRANSCRIPT_SHA" \
  --evaluator-receipt "$P2_REVIEWED_ORACLE_EVALUATOR_RECEIPT" \
  --out "$P2_ORACLE_SCORE_REPORT"
```

The reporter rejects mismatched evidence, missing or duplicate programs, invalid case positions and replay disagreement on a judged skill. It counts disagreements on unjudged skills separately. This interface prepares and reads evidence. The department run and candidate replay require separate execution approval.
