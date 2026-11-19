# P2-R department-server launch and log evidence

The launcher stages one phase per new output directory. Qualification covers five fresh launches in each of the three archived configurations, followed by the two open-sampling controls. Regeneration uses three separate output directories and compares each complete run with its pinned archive. The runner uses the original task, sampling and comparison settings from the [retained worklist](DEPARTMENT-REGENERATION-PREPARATION.md).

Use the [department GitHub download guide](DEPARTMENT-GITHUB-DOWNLOAD.md) to fetch the fixed source commit and check the archived inputs on the department computer.

## Offline review

From the source checkout, render the commands and expected record schema. Run the tests using local synthetic fixtures.

```sh
python3 -B experiments/rq-c/launch_department_regeneration.py plan
python3 -B -m unittest discover -s experiments/rq-c -p test_launch_department_regeneration.py -v
```

To compare two saved exports without contacting their collector, use the following command. The diagnostic reads the host identity and interval from the supplied exports. Phase acceptance also compares this identity and coverage with the approved allocation and actual recorded phase boundaries.

```sh
python3 -B experiments/rq-c/launch_department_regeneration.py audit-logs --before logs-before.json --after logs-after.json
```

Exit 0 means the two captures support a complete comparison with zero new relevant events. Exit 1 preserves newly observed events for investigation. Exit 2 indicates invalid or incomplete evidence.

## Before the authorized launch

Keep the supervisor's actual reply, the plan it approves, and the operator's reviewed approval receipt in a private project-local directory. Verify the sender from the original reply or equivalent authentic record. Pin the SHA-256 of the reviewed receipt independently of the launcher input. The launcher compares source bytes and receipts. Authenticating the human sender is part of the operator's review.

The approval receipt schema is `aijade.p2-r.department-execution-approval.v1`. Populate these fields from the reply, agreed plan, actual build and department host allocation.

| Field | Recorded value |
| --- | --- |
| `schema`, `scope`, `phases` | The schema above, scope `P2-R-department`, and the approved phases from `qualification` and `regeneration`. |
| `reviewedDraftSha256`, `worklistSha256` | The reviewed November 18 draft SHA-256 reported as `departmentPlanDraftSha256` by the worklist, and the canonical worklist SHA-256 reported by the offline command plan. The separately bound approved plan may incorporate the actual reply. |
| `supervisorReply` | Receipt-local relative `path`, exact `sha256`, zoned `receivedAt`, and the same operator-verified `reviewedSender` across the two phases. |
| `approvedPlan` | Receipt-local relative `path` and `sha256` of the agreed plan. |
| `sourceCommit` | Full commit of the clean checkout. |
| `logHistorySince`, `notBefore`, `notAfter` | Zoned times. The baseline query begins before the allocated execution window. The allocated window agrees with the department schedule and reply. |
| `host` | Stable nonempty `machine`, `boot`, `os`, `gpu`, and `driver`, plus the assigned `allocation`. The GPU identity identifies the actual assigned device, such as its device UUID. |
| `ollamaUrl`, `ollamaVersion` | Exact allocated endpoint with explicit port and no credentials, and its observed server version. |
| `build` | Receipt-local `directory`, relative `rqcDll` and `substrateDll`, and `files` mapping every regular file in the frozen build directory to SHA-256. Include dependency, runtime-config and manifest files. |
| `dotnet`, `logCollector` | Each has an absolute resolved executable `path` and exact `sha256`. The log collector may also specify a receipt-local `config.path` and `config.sha256`, which the launcher passes only after verifying the pinned file. |

The department log collector is selected when the OS, available journal or exporter and permissions are known. It is a read-only executable called with `--since` and `--until` as zoned timestamps. It exports one UTF-8 JSON document on stdout, with `schema` set to `aijade.p2-r.department-log-capture.v1`, actual `host` identity as above, the requested `since` and `until`, and `sources` with both `system` and `gpu`. Each source provides:

- `sourceId` for the actual journal/channel and `querySha256` for the unchanged collector and relevance filters, excluding the moving time bounds. Keep the source commands and access evidence.
- `complete` as a literal Boolean, plus `readableFrom` and `readableUntil` for the verified retained interval. Permission denial, unconfirmed retention or incomplete visibility must produce an error or `complete: false`. An empty event list is valid when independent retained-interval evidence establishes query coverage.
- `events` with unique stable `id`, zoned `at` and source event `record` for each relevant recorded error. Include applicable hardware faults, service crashes and unexplained interruptions. Keep raw event text in the private bundle.

The pre/post queries use the same source identities and relevance filters. The before cutoff is captured immediately before the baseline export and the post cutoff after the final operation. The post export retains the same historical prefix and extends through the phase end. Missing coverage or a changing historical prefix rejects the phase. New events in the covered phase trigger investigation even when all subprocesses exited successfully. These checks rely on complete and correctly identified source exports from the approved collector.

For an allocation with Linux, a local system journal and an NVIDIA device, see the [AIJADE read-only journal collector](DEPARTMENT-JOURNAL-COLLECTOR.md) for the pinned configuration, access requirements and the limits of retained-journal evidence.

For a reviewed allocation that uses WSL 2 with a Windows model host, the
[Windows host guide](DEPARTMENT-WINDOWS-WSL.md) describes the separate
host event collector and the WSL dependency check.

## Execute in the agreed window

The following invocations consume actual reviewed evidence. Use a new private bundle path under the AIJADE workspace, outside the source checkout or below its ignored `.runtime`. Keep the frozen checkout clean, with the approved build material outside tracked source. Qualification acquires a checkout-local allocation lock, exports the baseline before loading any model, independently confirms each model is out of the assigned service's resident set, then retains the exact subprocess/log records and post export. The assigned GPU still needs operational isolation from other users. Model unloading is checked by `/api/ps` after the documented empty generate request with `keep_alive: 0`. [Ollama generate API](https://docs.ollama.com/api/generate) · [Ollama server response for unloading](https://github.com/ollama/ollama/blob/v0.4.0/server/routes.go)

```sh
python3 -B experiments/rq-c/launch_department_regeneration.py run qualification \
  --approval "$P2_APPROVAL_FILE" --approval-sha256 "$P2_REVIEWED_APPROVAL_SHA" \
  --bundle "$P2_NEW_QUALIFICATION_DIR"
```

Review the completed qualification and its raw captures, independently pin its `phase-result.json`, then use that pin for regeneration. Re-audit verifies the receipt, raw bound files, all 15 launches, both controls, unload evidence and complete pre/post coverage. It also checks each capture's configuration attestation when the approval pins a config. Regeneration produces its own phase and comparison records. When a later assigned window has a separately reviewed receipt, pass the original qualification approval and its trusted SHA-256 as additional arguments. The stable technical plan, verified supervisor identity, source and build, endpoint, host, GPU and collector executable digest must still match. Each phase uses its own actual allocation and coverage window. The regeneration baseline must reach back to qualification's end on the same sources and queries. A lost or changed overlapping entry, uncovered gap, or relevant intervening event blocks the launch.

```sh
python3 -B experiments/rq-c/launch_department_regeneration.py run regeneration \
  --approval "$P2_REGEN_APPROVAL_FILE" --approval-sha256 "$P2_REVIEWED_REGEN_SHA" \
  --qualification-bundle "$P2_QUALIFICATION_DIR" \
  --qualification-receipt-sha256 "$P2_REVIEWED_QUALIFICATION_SHA" \
  --bundle "$P2_NEW_REGEN_DIR"
```

For separate allocation windows add `--qualification-approval "$P2_APPROVAL_FILE" --qualification-approval-sha256 "$P2_REVIEWED_APPROVAL_SHA"`. A phase with incomplete artifacts, divergence during qualification, missing error coverage or a new relevant error preserves its directory and cannot release regeneration. A completed regeneration can have scientific differences from the archive. The launcher records those differences for the subsequent paired analysis and exploratory re-tally.

After regeneration is accepted, use its original approval and the complete phase receipt to prepare the [P2-R Node replay and process evidence](DEPARTMENT-EXPLORATORY-ORACLE.md). The replay carries forward the approved plan and reply and uses its own reviewed process identity and allocation window.

The worklist and tests are offline preparation. The formal department phases and separate follow-on experiments await the actual reply and allocated host.
