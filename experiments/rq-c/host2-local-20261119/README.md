# P2-R on host 2, 19 November 2026: a deviation record

**Status: deviation from the reviewed plan. Not a replacement for the archived P2 results.**

The P2-R worklist was run from 06:34 to 07:42 UTC on 19 November 2026 on host 2, the Windows machine with the recorded CPU errors, under WSL 2. The run took place before the supervisor's reply to the P2-R plan and not on the department server.

- **Runner:** `b6d44d5742eb98008f40df57ce1aba2ad1f623a2`.
- **Service:** Ollama 0.40.16. The archived runs used 0.40.0 on the same host, with the same model digests.
- **Queue:** all 20 tasks completed:
  - five qualification passes for each group;
  - two open-sampling controls;
  - one full regeneration for each group (template A, template B, second family).

The supervisor's review of 21 November accepts this run as a deviation record. It will be used only as one row of the "same service version, different device" comparison once the department server's results exist. P2's main results come from the department server. (Added 26 November 2026: the department runs took place on 24 November 2026, with deviations; see [`../department-20261124/README.md`](../department-20261124/README.md).)

## Contents

- `delivered/`: the 75 files of the delivered release, byte for byte. `delivery-manifest.json` lists the other 74 with SHA-256 and size.
  - `delivered/README.md` and `delivered/outcome.json` are the release's own statements, including its list of deviations.
  - Private host logs, host identities and configuration stayed on the host and are not part of the release.
- `mac-verification/verify.py`: a read-only check. It calls no model and runs no program.
- `mac-verification/verification.json`: the output of that check, written on 20 November 2026.

## What the verification found

- **Manifest:** all 74 manifest entries match in hash and size.
- **Repeats:** across the five qualification passes of each group, trial records differ only in `durationMs`.
- **Oracle and verifier:** for regenerated programs whose code matches an archived program byte for byte, the execution verdict matches without exception (6,925, 6,850 and 5,922 executions). The verifier's majority verdict also matches for every program hash present in both runs (51, 46 and 34 programs).
- **Generated programs:** the regenerated programs differ from the archived ones on a few tasks in every group.
- **Consequence:** false-discovery rates are higher than in the archive in all three groups, by 0.017–0.026 (note of 26 November 2026: exact differences 0.016 to 0.026; 0.017 is the difference of the rounded rates).

It cannot yet be determined whether the change in the generated programs comes from the service version or from something else. Agreement across repeats on host 2 does not show whether its CPU faults affected the archived or the new outputs.

Reproduce from the repository root:

```
python3 -I experiments/rq-c/host2-local-20261119/mac-verification/verify.py
```
