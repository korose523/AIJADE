# Explicit segmented mutation exclusion candidate

Implementation and offline controls only. No live nested load, qualification
window, model request, renderer request or heldout construction was started by
this work. Historical P4 refusal and original source are untouched.

The only installed source changes are `experiments/ch7/mac_process_guard_v3.py`
and the new `tests/shell/test_segmented_capture.py` in the independent W5 tree.
The original guard is retained under `source-before`, the initial and final
diffs are retained separately, and each earlier control generation remains.

## Policy and raw evidence discriminator

The existing schema-3 lifecycle container remains compatible. New coordination
requires the exact policy pair:

```json
{
  "coordinationMode": "segmented-census-mutation-v1",
  "coordinationSchema": "aijade.mac.segmented-census-mutation.v1"
}
```

The raw observation repeats both values, contains exactly `before` and `after`
entries in `coordinationLocks`, and contains `segmentedApiClock`. It cannot claim
a legacy `coordinationLock`. The legacy branch rejects any of the new raw mode,
schema, lock-population or API-envelope fields. Unknown/mixed policy values
refuse. The root-owned execution-decision check must additionally prevent the
new mode from executing under a consumed legacy scientific plan.

## Actual phase order and exclusion

Both sequence and task scopes still perform independent real observations on
their own original clocks. Each observation does:

1. Complete before-phase daemon identity and executable-content reads outside
   the mutation lock, recording actual entry and completion.
2. Record the actual lock-request entry, acquire the same bounded lock used by
   identity-ready finite launches, and perform the complete before native graph,
   owned RSS and listener work while held. Release with the actual identity and
   clock witness.
3. Make the actual bounded API read outside the mutation lock, with its own
   actual entry/completion envelope.
4. Perform fresh complete after-phase daemon reads, then independently acquire
   and release the same short lock around after graph/RSS/listener work.
5. Construct current complete lifecycle views and remember the actual frames
   outside the mutation lock; read and validate the exact complete journal
   prefix. Independently recompute the observation verdict.

Each phase therefore excludes an identity-ready but not-yet-registered shim
from the native/RSS/listener snapshot. Both full daemon reads remain within the
original whole-observation clock; no byte, identity or actual parent wait is
omitted. There is no cross-scope cached PASS and no shared fake capture.

Independent validation requires source-bound whole evidence, exact phase-lock
population and scope discriminator, the same device/inode across both phases,
actual acquisition minus request no greater than 1.25 seconds, the original
reported wait bound, and each phase's held interval no greater than 1.25 seconds.
The actual daemon read ends before that phase's request; graph, RSS and listener
intervals lie inside its lock. Before release precedes API; API completion
precedes after daemon-read entry. Actual API duration lies within the recorded
envelope. Original 2.5-second complete observation and three-second continuity
rules remain unchanged. Per-phase held-time acceptance is a necessary bound,
not a proof of global fair scheduling or nested-load capacity.

Moving the complete lifecycle-view copy outside the capture lock permits valid
owned launch/reap transitions between native frames. Their actual typed journal
events, birth/release times and actual parent-wait outcomes remain mandatory.
The existing typed ownership validator handles those envelopes; no stale view
or absent-PID inference is used to manufacture success.

## Offline controls and unresolved live gate

`controls-final-04.json` binds the exact final guard and test hashes. All 75
bounded tests passed: 19 new segmented controls plus the existing lifecycle-guard
and exact-prefix cursor suites, with zero skip/error/failure. The new controls
include real threads and real local flock with fake readers: both threads are
held inside unfinished daemon reads until finite-dispatch code obtains the actual
lock and releases them. No wall-speed threshold substitutes for that ordering.

Other controls independently replay full native/lifecycle fixtures; they accept
a proven task launch and normal actual parent wait wholly between native frames,
and reject omitted waits, phase work outside a real lock envelope, mode/schema
substitution, lock replacement, unsupported budgets, API/daemon reordering,
altered same-prefix views, old-scope prefix regression, missing RSS/listener/API
proof and nonzero exits. Legacy fixture acceptance remains unchanged.

These tests are neither Mac backend qualification nor real nested-load evidence.
Real full-scope engineering validation must still establish actual end-to-end
costs, journal-prefix growth, both controller observers, sustained launches,
handoff continuity, raw process identities and actual terminal waits. Any refusal
must be retained. Only an accepted complete engineering load may precede a
separately frozen new scientific qualification attempt.
