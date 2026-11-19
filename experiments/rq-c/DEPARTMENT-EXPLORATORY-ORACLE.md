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

## Collect per-case evidence from the approved evaluator

Use `CaseEventWriter` and `case_binding` in `department_oracle_capture.py` at the approved evaluator's own observation points. The writer accepts event data and an output stream. Open a new evidence file for each run. Assign a unique 64-character lowercase hexadecimal `sessionId` and use it in the invocation contract, header, every case event and closure. Set the same `evidenceScope` in the invocation contract and both capture boundaries. Capture start and end are explicit UTC observations. The verified capture must start at or after the observation window closes in the accepted regeneration receipt.

- Record `VARIANT_START` at the start of each `asRun`, `entry` and `entryAndTest` trial. Supply its group, task ID, exact code SHA-256 and pinned case timeout. Record `PROGRAM_SKIP` only for a manifest row with the historical lexical disposition.
- Record each `CASE_RESULT` after comparing it with the pinned reference under the specified rule. Supply the original `caseIndex`, `caseBindingSha256` from `case_binding`, monotonic elapsed nanoseconds, and the observed `PASS`, `FAIL` or `TIMEOUT`. The binding hashes the task, original index and full pinned case-list digest, which includes fixtures and expected values. The evidence stores case identities and typed outcomes.
- Record `VARIANT_FINISH` with `CASE_RESULTS`, `NO_CALLABLE` or `SETUP_ERROR`. With a timeout, retain the preceding observations and close after the observed timeout case. An evaluator or recorder stop yields an incomplete capture. The importer requires the complete ordered case list or a prefix ending in an explicit timeout.
- At session closure capture the ending identity with `CAPTURE_FINISH`. Both capture boundaries carry the manifest file digest and the corresponding evaluator, runtime, arguments, version and environment digests. The validator checks one session and a contiguous event sequence from opening through closure.

The original archival Node audit emitted aggregate failures and did not retain the original timeout index or exact Node runtime version. Its source and rule identity are kept for comparison. The adapter attaches the writer to the original evaluator's entry, case comparison, failure, timeout and skip observations. The archived AIJADE substrate records describe the original Jint execution. The separately approved Node replay captures exploratory evidence with the operator's independent review of the running process and its observations.

## Launch one approved department replay

The accepted regeneration phase and exact replay manifest determine the program population. The launcher constructs evaluator stdin from those programs and the pinned bench. Its plan action renders the evidence identities for review.

```bash
p2_replay_input=(
  --regeneration-bundle "$P2_REGENERATION_DIR"
  --phase-receipt-sha256 "$P2_REVIEWED_REGENERATION_SHA"
  --replay-manifest "$P2_ORACLE_MANIFEST"
  --replay-manifest-sha256 "$P2_REVIEWED_ORACLE_MANIFEST_FILE_SHA"
)
python3 -B experiments/rq-c/launch_department_oracle_replay.py plan \
  "${p2_replay_input[@]}" --session-id "$P2_REPLAY_SESSION_ID"
```

The operator's `aijade.p2-r.department-oracle-replay-approval.v1` record carries forward the supervisor reply and approved plan of the accepted regeneration. Verify the recipient's allocation and actual host, source checkout, evaluator artifact and exact Node binary and environment. The approved plan and reply remain the authority for any schedule amendment. The original P2-R plan places the new stages on or after 2 December 2026.

| Field | Reviewed evidence |
| --- | --- |
| `schema`, `scope`, `evidenceScope` | The replay approval schema above, `P2-R-department-oracle-replay`, and `OPERATOR_REVIEWED_EXTERNAL_REPLAY`. |
| `binding`, `regenerationApprovalSha256`, `evaluatorSha256` | Copy from the plan output tied to the accepted regeneration. |
| `sessionId`, `manifestFileSha256`, `evaluatorInputSha256` | Copy from the plan's `invocation`. Choose a new session for each independently reviewed attempt. |
| `sourceCommit`, `hostName`, `notBefore`, `notAfter` | Full clean replay checkout commit, actual host name and approved zoned times after regeneration closure. |
| `node` | Resolved executable `path`, its `sha256`, and the independently checked environment object with the runtime environment schema below. The launcher fixes locale environment variables to `C` and timezone to `UTC` for the evaluator and probes. |
| `supervisorReply`, `approvedPlan` | Receipt-local relative paths and digests. The reply includes the same reviewed sender and received time. The launcher checks the reply and plan digests against the approved regeneration record. |

```bash
python3 -B experiments/rq-c/launch_department_oracle_replay.py run \
  "${p2_replay_input[@]}" \
  --regeneration-approval "$P2_ACCEPTED_REGENERATION_APPROVAL" \
  --approval "$P2_REPLAY_APPROVAL" --approval-sha256 "$P2_REPLAY_APPROVAL_SHA" \
  --bundle "$P2_NEW_REPLAY_DIR"
```

Use a new private directory in the AIJADE workspace. The launcher accepts a single approved Node executable and its generated evaluator. It retains the exact input in `evaluator-input.json`, full stdout in `evaluator-stdout.json`, and raw stderr in `evaluator-events.jsonl`. The process receipt `process-receipt.json` records whether the process started, its return code and termination path, the execution interval, the approval digest, and hashes and sizes for all three streams. It keeps a refusal and partial streams when the process cannot complete. The launcher also retains the original operator replay approval as `execution-approval.json`.

Success requires exit zero, stable runtime snapshots, evaluator closure inside the measured process and approved interval, and agreement between the entire stdout array and the case events. The readback checks every program and variant, including original arguments and reference values for reported failures. The accepted result writes normalized `case-events.jsonl`. The independent operator review pins all 13 files for formal scoring, including the execution approval, process receipt, private stdin, stdout and sidecar. Keep those files private. The analysis commands recheck the exit facts, exact byte hashes, output population and receipt linkage. A typed synthetic route remains available for offline controls.

## Inspect the instrumented Node entry point offline

The adapter generates an evaluator artifact from the exact pinned historical Node source. The evaluator continues to consume the original `tasks`, `pairs` and `dropped` fields and to write the same aggregate report to stdout. It sends case evidence to stderr. The adapter's `artifact` and `bridge` commands produce and verify files. An approved runner supplies stdin and records the process outcome.

```bash
python3 -B experiments/rq-c/department_oracle_adapter.py artifact \
  --out "$P2_CASE_CAPTURE_DIR/evaluator.bin"
```

Prepare input from the accepted manifest by flattening its groups in sorted group order and preserving each group's manifest program order. Retain the existing candidate, task and rule payload, and add an `observationContext` object with `sessionId`, `evidenceScope` and `manifestFileSha256` identical to the invocation contract. Serialize the input with ASCII escapes, as the historical runner did. Retain the exact private input bytes and place their SHA-256 in `invocation.json` as `evaluatorInputSha256`. The evaluator hashes the bytes it receives on stdin before text conversion, and reports that digest together with its session, scope and manifest at both stream boundaries. Each variant start reports the actual case-list digest, retained case indices and timeout. These are checked even when a variant returns before the first case or stops at a timeout.

Preserve the complete stderr stream as `evaluator-events.jsonl`, plus the actual process exit status and full legacy stdout for review. Send stdout and stderr to separate files or drain both streams concurrently. The closure event establishes the end of the recorded evaluator stream. The operator checks successful exit, complete stdout and the capture context before issuing the named review. An incomplete stream is refused and should be retained as run evidence.

```bash
python3 -B experiments/rq-c/department_oracle_adapter.py bridge \
  --replay-manifest "$P2_ORACLE_MANIFEST" \
  --replay-manifest-sha256 "$P2_REVIEWED_ORACLE_MANIFEST_FILE_SHA" \
  --capture-directory "$P2_CASE_CAPTURE_DIR" \
  --evaluator-events-sha256 "$P2_EVALUATOR_EVENTS_SHA"
```

The bridge writes `case-events.jsonl` after checking the input and complete evaluator stream. Use the artifact and bridge commands for inspection and synthetic controls. The capture, transcript and score commands re-derive the normalized events from `evaluator-events.jsonl` and expect an exact byte match. An external replay also requires the complete launcher process evidence above.

## Record the runtime artifacts and review their identities

Place these files beneath an AIJADE-local capture directory.

| File | Evidence |
| --- | --- |
| `evaluator.bin`, `node.bin` | Exact bytes of the reviewed evaluator artifact and Node executable. Preserve them in the capture directory under these names. |
| `version-before.txt`, `version-after.txt` | The observed Node version line before and after the session. Both reads must agree. |
| `environment-before.json`, `environment-after.json` | `aijade.p2-r.department-oracle-node-environment.v1` with `runtime` set to `node`, plus `runtimeVersion`, `platform`, `architecture`, `osRelease`, `locale` and `timeZone`. Both snapshots must agree. |
| `invocation.json` | `aijade.p2-r.department-oracle-invocation.v1` with `sessionId`, `evidenceScope`, `manifestFileSha256`, `referenceReplayEngineSha256`, `benchSha256` and the exact ordered `arguments` after the evaluator artifact. Record the actual use of the pinned runtime and evaluator in the operator review. |
| `case-events.jsonl` | The complete session stream emitted as `aijade.p2-r.department-oracle-case-event.v1`. |

Capture only the listed environment fields. Keep private arguments outside any published evidence. The operator confirms the observed evaluator and runtime artifacts, process outcome, version, arguments and environment against the approved run identity, then issues `aijade.p2-r.department-oracle-capture-review.v1` independently of the evidence import. The review contains `evidenceScope`, the manifest's `binding`, `manifestFileSha256` and the `fileSha256` mapping. Include all 13 files for an external process bundle. Its `attestation` contains `operatorId`, a UTC `reviewedAtUtc` at or after process completion, and `decision` set to `ACCEPTED_CAPTURER_AND_EVIDENCE`. Use `OPERATOR_REVIEWED_EXTERNAL_REPLAY` for the scope after an approved run and supply the independently obtained SHA-256 of the operator review. The digest pins the named attestation as received. Authenticity is established by the independent review and its chain of custody.

## Verify, produce and score the capture

```bash
p2_capture_inputs=(
  --regeneration-bundle "$P2_REGENERATION_DIR"
  --phase-receipt-sha256 "$P2_REVIEWED_REGENERATION_SHA"
  --replay-manifest "$P2_ORACLE_MANIFEST"
  --replay-manifest-sha256 "$P2_REVIEWED_ORACLE_MANIFEST_FILE_SHA"
  --capture-directory "$P2_CASE_CAPTURE_DIR"
  --operator-review "$P2_OPERATOR_REVIEW"
  --operator-review-sha256 "$P2_OPERATOR_REVIEW_SHA"
)

python3 -B experiments/rq-c/rescore_department_oracle.py capture \
  "${p2_capture_inputs[@]}" --out "$P2_VERIFIED_ORACLE_CAPTURE"

python3 -B experiments/rq-c/rescore_department_oracle.py produce \
  "${p2_capture_inputs[@]}" --out "$P2_REVIEWED_ORACLE_TRANSCRIPT"

python3 -B experiments/rq-c/rescore_department_oracle.py score \
  "${p2_capture_inputs[@]}" \
  --replay-transcript "$P2_REVIEWED_ORACLE_TRANSCRIPT" \
  --replay-transcript-sha256 "$P2_REVIEWED_ORACLE_TRANSCRIPT_SHA" \
  --out "$P2_ORACLE_SCORE_REPORT"
```

The verified capture contains normalized `aijade.p2-r.department-oracle-observations.v1` and `aijade.p2-r.department-oracle-evaluator-receipt.v1` records with the raw event and review identities. The transcript in `aijade.p2-r.department-oracle-replay-transcript.v2` retains those identities, ordered `failedCaseIndices` and `timedOutCaseIndex` where observed. The scorer verifies the capture again and requires a byte match with the independently pinned transcript. It rejects baseline replay disagreement on a judged skill and counts disagreements on unjudged skills separately.

Use `SYNTHETIC_FIXTURE` and `--evidence-mode synthetic` for an offline fixture. Direct normalized observations and evaluator receipts are accepted only in that mode. Synthetic results carry the scope `SYNTHETIC_REPLAY_TRANSCRIPT_SCORED`. These commands read evidence and run zero candidate evaluations. Department regeneration and actual evaluator operation require separate execution approval.
