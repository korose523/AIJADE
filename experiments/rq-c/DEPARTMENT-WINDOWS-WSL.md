# P2-R with a Windows model host and a WSL 2 runner

This preparation route uses a WSL 2 Linux checkout to run the existing P2-R
commands and Windows PowerShell to read the model host's event logs. Its use
depends on the actual departmental allocation and the reviewed execution
plan. It does not confer device qualification.

## Prepare the toolchain

1. In Windows PowerShell, use `wsl.exe --list --verbose` to confirm the
   allocated distribution is on WSL 2. Use the Linux filesystem inside the
   distribution for the checkout, build outputs and private receipts.
   Download the exact GitHub commit with the
   [department source guide](DEPARTMENT-GITHUB-DOWNLOAD.md), which preserves
   the tracked bytes by disabling Git's newline conversion before checkout.
   [Microsoft WSL commands](https://learn.microsoft.com/windows/wsl/reference)
2. Provide Linux-native Git, Python 3.12 or later, `findmnt` from
   util-linux, the .NET SDK selected by
   [global.json](../../global.json), and Node for the exploratory replay.
   Install or select Linux builds in the approved environment. Record
   resolved executable paths and the exact runtime identities at freeze.
   WSL interop must be able to start the assigned Windows PowerShell
   executable. The Windows host supplies the NVIDIA driver and its own
   `nvidia-smi.exe` for host evidence.
   [Microsoft WSL interop](https://learn.microsoft.com/en-us/windows/dev-environment/wsl-interop) ·
   [NVIDIA CUDA on WSL](https://docs.nvidia.com/cuda/wsl-user-guide/)
3. Run the read-only check from the clean checkout. An explicit
   `--powershell` value is an absolute WSL path to the native executable.
   Keep the output with the private preparation receipts.

```sh
python3 -B experiments/rq-c/check_department_wsl.py \
  --expected-commit "$P2_REVIEWED_COMMIT"
```

The check verifies the Linux tools, Windows interop and the worklist
derived from the archived inputs. The path representation in the worklist
uses forward slashes on both operating systems. Its SHA-256 remains
`04bf4f7f96b41b888ce22f81de4bf533b3d3edc53d38a0f3f6828785b898b91d`.
The dependency check sends no model requests and reads no live event logs.

## Bind the host log collector

Use a private reviewed configuration with schema
`aijade.p2-r.windows-event-collector.v1`. Populate it using the assigned
Windows account, host, GPU and actual model service. Material used in a
formal approval is pinned byte for byte.

| Configuration field | Source |
| --- | --- |
| `allocation` | Reviewed allocation identifier |
| `powerShell`, `powerShellSha256` | Resolved local Windows PowerShell executable and its digest. Under WSL use the absolute mounted Linux path to the native `.exe`. |
| `nativeHelperSha256` | Digest of the tracked `collect_department_windows.ps1` helper |
| `nvidiaSmi`, `nvidiaSmiSha256`, `gpuUuid` | Absolute local Windows drive path to the NVIDIA executable, its digest and the allocated physical GPU UUID |
| `serviceNames`, `applicationExecutables`, `applicationProviders` | Exact reviewed service and application identities for relevant Windows events |

```sh
python3 -B experiments/rq-c/collect_department_windows.py \
  --check-config "$P2_COLLECTOR_CONFIG" \
  --expected-config-sha256 "$P2_COLLECTOR_CONFIG_SHA" \
  --expected-allocation "$P2_ALLOCATION"
```

The read-only config check uses only the reviewed configuration bytes.
For an approved live capture, the launcher pins the collector,
configuration and expected host, and passes the observed cutoff bounds
through `--since` and `--until`. Set the approved `logCollector.path`
to the resolved, executable `collect_department_windows.py` and
`logCollector.config.path` to the configuration relative to the receipt.
Keep the verified Linux Python first on the runner's PATH. Pin the Python
collector, native helper and configuration independently. Use the effective Windows execution policy
and local account permissions for the helper. Verify that the account can
read System and Application records and that retained records bracket the
approved interval. The model and GPU work must remain on the allocated
host. This Windows collector covers the host's logs. A model service running
inside WSL needs its own reviewed service-log coverage.

The collector retains Windows host and boot identity, the approved GPU UUID
and driver, relevant event XML, and coverage anchors. Relevant WHEA, NVIDIA,
shutdown and model-service faults remain visible to
[the existing phase auditor](DEPARTMENT-REGENERATION-LAUNCH.md).
Missing access, changed anchors, incomplete retention or mismatched identity
block acceptance. Keep real event XML and the approval bundle private.

The Windows CI job checks the frozen worklist, parses the native PowerShell
helper, verifies the event query interval on the hosted runner, and exercises authored event fixtures.
Actual interop, event channel
visibility, runtime identity and an approved live phase remain separate
checks for the assigned machine.
