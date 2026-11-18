# P2-R department journal collector

This adapter runs on the assigned Linux NVIDIA host, reads the local system journal and writes one UTF-8 JSON capture to standard output. It makes no network requests, loads no model, changes no journal settings and writes no journal entries. A host with a different driver, a different log source or inadequate read visibility needs a separately reviewed collector under the same launch contract.

## Offline verification

From the source checkout, run both synthetic control suites. These tests call a scripted journal reader and local synthetic subprocesses. They make no queries to a real journal, GPU or department host.

```sh
python3 -B -m unittest discover -s experiments/rq-c -p test_collect_department_journal.py -v
python3 -B -m unittest discover -s experiments/rq-c -p test_launch_department_regeneration.py -v
```

The [P2-R launcher](DEPARTMENT-REGENERATION-LAUNCH.md) can audit two saved captures again without calling the collector.

## Configure after the reply and host assignment

Use the actual department reservation, PCI address, resolved journalctl executable and source bytes. Verify that the assigned device exposes its UUID at `/proc/driver/nvidia/gpus/<PCI address>/information` and its loaded module version at `/sys/module/nvidia/version`. Confirm that the relevant model service is a declared system unit in the local journal namespace. Verify the assigned account can read that system journal through the required retention interval. Keep this configuration and captured logs private in the project workspace.

| Configuration key | Required value |
| --- | --- |
| `schema` | `aijade.p2-r.linux-journal-collector.v1` |
| `allocation` | The approved allocation identifier. The collector receives this identifier from the reviewed configuration. |
| `pciAddress` | The assigned lowercase PCI address including its domain, in `dddd:bb:dd.f` form |
| `journalctl` | Absolute resolved path to the installed journalctl executable |
| `journalctlSha256` | SHA-256 of those executable bytes |
| `serviceUnits` | Explicit unique systemd service names, for example the actual Ollama system service |

Pin the collector executable with `logCollector.path` and `logCollector.sha256` in the reviewed approval. Add `logCollector.config` as `{"path": "collector.json", "sha256": "<exact SHA-256>"}` for the configuration beside the approval. The launcher checks the config digest before and after each call and expects the collector to report it. Other collectors can keep the original executable-only contract. If running the adapter directly on the approved host for review, the same configuration path is passed in `AIJADE_P2_LOG_CONFIG` and the two arguments identify the requested zoned interval.

The capture's stable host fields are the Linux machine ID, boot ID in 32 lowercase hex characters, `Linux <kernel release>`, the assigned NVIDIA GPU UUID and `nvidia <loaded module version>`. Use these observed values in the reviewed host record. The separate allocation identifier still comes from the approved reservation.

## What the capture establishes

The adapter queries the local system journal for the observed boot, obtains one retained system entry and one retained kernel entry at or before the requested start, queries the half-open interval and checks both start anchors again. It requires the actual clock to have reached the requested end before collection and checks the host and device identity again. For a quiet window, the end of declared readability comes from the completed query at or after the cutoff and the observed lower-bound witnesses, so the operator need not create a later log event to finish the capture. A missing retained anchor, changed anchor, permission diagnostic, truncated output, another host or boot, loss marker or exhausted time or byte budget fails the capture. The six read-only invocations, including the journalctl version query, share one 90-second limit and a 32 MiB limit on combined stdout and stderr bytes. Truncation fails the entire capture.

The two source views share the system journal. The system view retains priority 0–3 messages, recognized hardware fault markers and failures tied to the approved service units. The GPU view retains recognized GPU failures from the kernel or an approved service. The venue must confirm that the approved journal and filters contain the relevant department telemetry. A reboot changes the identity and breaks comparability. Coverage describes readability of these retained sources and exact queries. It cannot establish that faults which never reached the journal were absent.

The capture retains the source identifiers, query scope and executable digests, requested window, collection times, command and output digests, raw coverage anchors and counts of queried entries. Relevant events keep their original journal JSON line and opaque cursor identity. Nonselected journal bodies stay out of the bundle. Because relevant entries and anchor records can still contain sensitive operational text, review the private evidence before any later sharing.

The offline controls are evidence about the collector and its integration, while the actual prescribed host and its source visibility await assignment. The P2-R qualification and regeneration have no new results from these checks.
