# Listener transcript v2: pure, inactive preparation

This directory contains the pure parser and verifier for the proposed native
READY listener capture. It performs no operating-system query, process launch,
clock read, file read, network access or result caching. Nothing here installs or
activates a new engineering or scientific mode. All tests use fabricated bytes,
clocks, source identities and canonical-state fixtures.

`listener_evidence.py` runs on Python 3.9. Its contract is described in
`contract.json`. `test_listener_evidence.py` includes the actual `_read_listeners`
function extracted from the fixed e918 guard source. That function executes
against a fake lifecycle and clock; the original global command is checked in
each positive comparison. The function bytes and original full-source SHA are
recorded in `oracle-source-binding.json`. No legacy source was changed.

## Integration contract

The future caller must select `lifecycleExecMode=native-ready-release-v1` and the
closed six-field `nativeExec` policy supplied by the native adapter. It must also
provide the closed listener policy:

```json
{
  "mode": "complete-managed-lsof-transcript-v1",
  "moduleSha256": "ACTUAL_FROZEN_MODULE_SHA256_REQUIRED",
  "command": ["/usr/sbin/lsof", "-nP", "-iTCP:11434", "-sTCP:LISTEN", "-FpfPtTn"],
  "executableSha256": "ACTUAL_FROZEN_LSOF_SHA256_REQUIRED",
  "maxSeconds": 0.5,
  "maxBytes": 65536
}
```

This example is documentation, not an executable policy. Placeholder hashes are
refused. The global command means all system-visible listeners selected by the
original TCP:11434 predicate. It does not add a process/PID filter and does not
claim to enumerate ports outside that fixed command.

The caller retains the exact handle returned by its own native `launch` call.
It captures real stdout/stderr and the actual return/exception, finishes the
original `ManagedProcess` wait, and obtains that handle's final
`evidence_for_handle(handle)` record. It must not select a handle using a shared
last-handle position. No earlier good record may substitute for a failed call.

Each retained raw stream is represented by `encode_capture(bytes)`, including
base64, exact byte length and SHA256. Acceptance stdout remains capped at 65536
bytes. Forensic retention is capped at 2 MiB **per stream**. If only a prefix is
available, use `truncated=True`; its `totalSha256` must be null and its known
`totalBytes` may be null. Such a capture always produces UNKNOWN. There is no
lossy text replacement and no invented full-stream hash.

The transcript records three internal monotonic times: entry, completed run and
completed parse. `derive_outcome(transcript, outer_clock)` always decodes and
parses the captured bytes again. The separate `outer_clock` has exactly
`startedMonotonic` and `finishedMonotonic`. The caller must measure it around the
whole listener operation, including scheduling, native launch, provenance reads,
actual wait, raw retention and parsing. The verifier requires this outer envelope
to contain the internal clocks and enforces 0.5 seconds on both. Capturing an
outer endpoint before these operations finish is a caller defect, not a faster
measurement. The pure module does not read a clock to repair missing evidence.

`verify_transcript(transcript, canonical_state, full_policy,
parser_source_sha256=..., caller_source_sha256=..., outer_clock=...)` repeats the
raw derivation and additionally binds the native lease and source proofs. The
caller must supply a fully validated canonical lifecycle state at the actual
observation cutoff, using its existing full-prefix validation path. This module
does not turn an arbitrary serialized state into a trusted journal or validate
the journal hash chain itself. The parser and caller SHA arguments must come
from the actual source files already pinned by the frozen runtime/source
closure. The module has no file I/O and cannot authenticate a caller's claims
about files by itself.

The native witness must bind the exact target command and lsof executable,
native adapter/C-source/binary hashes, stable before/READY/after provenance,
gated executable image, PID/birth/parent, and the original canonical
FINITE_REGISTER, RELEASE and actual zero Popen.wait events. Registration and
release event times fall inside their recorded phase brackets. The valid wait
partial order is `gateWritten <= actualReaped <= WAIT <= runCompleted` and
`returned <= runCompleted`. It deliberately allows the original reaper thread
to reap a very short child before the launch finally block returns. Nested
capture-lock metadata is recognized explicitly; the unchanged outer guard
retains responsibility for authenticating and timing the enclosing shared lock.

## Parser and outcome meaning

For unambiguous complete records, the projection is exactly the original
e918 fields: `pid`, `protocol`, `family`, `endpoint`, `socketState`. Every
f-delimited record and its original order survive. FD names remain present in
the full raw stdout, as the original record projection omitted the FD field.
Duplicate PID/FD records are not deduplicated; IPv4, IPv6, wildcards and original
endpoint spelling are not normalized. Extra processes are not filtered.

Version 2 additionally refuses malformed or ambiguous field order, orphan FDs,
duplicate selected fields, missing selected fields, non-ASCII/NUL data and
unknown tags. Ignored `Tkey=value` details retain the original positive field
projection. Complete TCP/IPv4-or-IPv6/LISTEN fields are required. A successful
empty stdout keeps the original positive empty-record semantics; a nonzero
return remains UNKNOWN. These stricter malformed-data rules are explicit and
are not silently backported into the original parser.

All observable adverse conditions are OR-combined into named reasons: missing
or nonzero return, capture exception, nonempty stderr, excess bytes/truncation,
decode/schema/hash failures, deadline violations, and source/lease/clock
binding failures. Any reason gives UNKNOWN and no usable records. A successful
result returns detached records and detached lease provenance. Mutating the
result cannot mutate canonical state or a later result.

Hashing raw bytes detects an altered encoding against its stored length/hash;
canonical lease binding separately detects a coherently rewritten command,
identity, birth, source generation or wait against the original canonical
record. A newly forged stdout plus a newly forged matching hash cannot be
distinguished from a new capture solely by these self-reported bytes. The
retained original sample, fixed source and packet hashes remain necessary for
archive authenticity. Neither self-hashes nor an OBSERVED result establish
OS/global completeness, research qualification, lock-contention acceptance or
scientific validity.

## Controls

Run only outside a real engineering window:

```sh
/usr/bin/python3 -B test_listener_evidence.py
```

The controls include exact 0.5 seconds and its next floating value; independent
outer/internal deadlines; stdout at 65536 and 65537 bytes; 2 MiB forensic cap;
stderr with exit zero; nonzero/missing/bool/float exit; actual wait/parent/birth
binding; future and missing waits; source/provenance generation changes;
encoding/hash corruption; coherent re-signed malformed/identity/command data;
strict schemas; mutation/alias separation; and unchanged multiplicity. These
are portable functional controls and have no OS/native/model acceptance claim.
