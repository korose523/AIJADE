# Launching the two known-case Mac repeats

The launch entry will run the same 20 ordered conditions twice. The Mac
qualification reply is pending. Both repeats and Table 7.3 are `NOT_RUN`.
The offline controls exercise the parent and terminal verification with
explicitly synthetic child subprocesses.

## Freeze the approved execution

Keep the supervisor's actual reply and the reviewed one-page qualification plan
as private original files. After receiving the reply, freeze a new clean
implementation commit Q whose
`experiments/ch7/mac-known-repeats-qualification/decision.json` has schema
`aijade.ch7.known-repeat-decision.v1`, status `SUPERVISOR_REPLY_CONFIRMED`,
`executionPlanPath`, `executionPlanSha256`, `qualificationPlanSha256` and
`replySha256`. The decision records digests. The original reply and plan stay
in their private files. The execution plan lives under the same tracked
qualification directory. It records the approved inputs for one finite block
and two isolated repeats:

- Schema `aijade.ch7.known-repeat-execution-plan.v1`, purpose
  `qualification_only`, `repeats` equal to 2 and `conditionSlotsPerRepeat`
  equal to 20.
- `databasePort` for the approved local test service.
- `toolsSha256` for the actual Python, dotnet and Docker executables. The
  keys are `python`, `dotnet` and `docker`.
- `watchdog` with positive integer `blockWallSeconds`,
  `rendererTimeoutSeconds`, `sustainedResourceSeconds`,
  `parentAllowanceSeconds` and `shutdownGraceSeconds`. The optional
  resource bounds `maxOwnedRssBytes`, `minAvailableBytes` and
  `maxSwapIncreaseBytes` are explicit integers or JSON null. The approved
  values control operational interruption. A technical stop is a refusal
  with captured evidence. The earlier fixed settling and admission phases
  remain historical.

Freeze the prebuilt test assembly and its complete dependency directory in
a separate B commit descending from Q, using the existing exact build manifest
format and the tracked path
`experiments/ch7/mac-known-repeats-qualification/frozen-build.json`. Keep
the actual prebuilt renderer, model asset, Godot wrapper, Godot executable
and sandbox profile inside AIJADE. The child checks the committed build
manifest, the listed files and the complete approved backend before execution.

Prepare a private digest-only approval record with schema
`aijade.ch7.known-repeat-approval.v1` and status
`SUPERVISOR_REPLY_CONFIRMED`. It includes `implementationCommit`,
`executionPlanSha256`, `qualificationPlanSha256`, `replySha256` and the
closed `backend` fields defined by `qualified_backend` in
`finite_construction_binding.py`. The caller supplies the independently
recorded SHA-256 for these exact bytes. The CLI checks both private originals
against the recorded digests. It copies the digest-only approval to the
private launch directory and binds it through the prelaunch and terminal
records.

The private local config uses schema `aijade.ch7.known-repeat-local-config.v1`.
Supply `buildFreezeCommit` and exact local paths for `client`, `model`,
`assembly`, `buildManifest`, `godot`, `realGodot`, `sandboxProfile`,
`dotnet`, `docker` and `dockerSocket`. Use the project-local Unix socket
for the test container and the provisioned local `AIJADE_TEST_DATABASE_URL`
from the shell. The child checks that the approved container exposes the
approved local port. Keep credentials out of the plan, approval and command
arguments.

## Run only after the reply and freeze

From the clean Q checkout with the project-local environment active:

```sh
python3 -B experiments/ch7/launch_known_repeats.py \
  --approval "$approval" --expected-approval-sha256 "$approval_sha256" \
  --original-reply "$private_reply" --qualification-plan "$reviewed_plan" \
  --config "$local_config" --scratch "$project_scratch" --output "$new_attempt"
```

Darwin, Python 3.11 or newer, psutil 7.2.2, the approved prebuilt backend and
the local test service are required. The parent creates a private new output
directory. Use a directory outside the clean Q worktree. An existing output
directory is refused. The parent records `approval.json`, `launch.json`,
the three known inputs, original repeat outputs, child logs and the ordered
terminal receipt. The second child begins after the first child's normal
exit, complete 20-condition terminal evidence, renderer/flow closure and
known process/database absence have all been checked.

The parent supervises each child for the approved block limit plus the approved
parent allowance. On interruption or expiry it gives the owned child its
approved cleanup grace after SIGTERM. If it must force the controller to
stop, the attempt is recorded as refused with descendant absence unverified.
The known-mode process registry retains actual starts and discovered
descendants across the workload. Missing or uncertain terminal absence stops
the sequence. The resulting parent receipt states whether the two known
repeats completed. The qualification acceptance step separately verifies
the formal launch, both original deliveries and decision agreement before
any fresh case or seed is created.

## Offline regression

```sh
python3 -B experiments/ch7/test_launch_known_repeats.py -v
```

The test children only write labeled archive-derived fixtures or sleep until
the test watchdog stops them. Production origin is reserved for the real
reply-bound launcher. None of the fixtures runs the Mac backend or constitutes
a qualification or held-out observation.
