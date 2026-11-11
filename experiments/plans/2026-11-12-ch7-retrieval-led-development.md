# Chapter 7: retrieval-led development qualification

Status: prospective development protocol. The earlier 2026-11-12 packet remains
an artifact replay; its initial retrieval did not cause its earlier execution or
rendering. This protocol tests a new path. No held-out cases or C1 comparison are
authorized or claimed by this protocol.

## Fixed inputs and sequence

Use the ten already-known cases H, I1–I8 and S1, the two unchanged historical
programs in `experiments/ch7/2026-11-12/selection.json`, and the existing unchanged
benchmark. No model calls, new labels, new tasks or human-review claims.

One .NET process retains ten separate owned PostgreSQL databases. In each case:
write a route cue through the authenticated perception API; retrieve it through
the memory API; parse the returned task ID, code SHA-256 and requested act; select
only a matching frozen catalogue program; execute that program (I4 explicitly
omits fresh execution); map its result and requested act into an allowlisted
intent. I5 retrieves the unusable program. S1 explicitly overrides the requested
comfort act with celebrate, preserving the known semantic counterexample.

Only after all ten prefixes finish may the controller start a fresh Godot client
session. Register each intent before sending its UDP packets. Wait for actual
client process exit and a sealed render-state file, then import the receipts and
continue admission, atomic promotion/authority/outbox writes, actual memory
delivery and second-round retrieval/guarded sandbox reuse on each original
case database. Reuse does not include a second rendering or model answer.

Keep the previous I1/I2 binding failures, I3 idempotency, I4 unknown execution,
I5 execution failure, I6 insufficient stage, I7 revocation, I8 rollback, and S1
semantic controls unchanged. Expected first promotions: H/I3/I7/S1; expected
second-round sandbox executions: H/I3/S1. These are development expectations,
not a comparative effect estimate or general success rate.

## Dataflow controls and verification

Before the measured batch, an actual API routing control changes the retrieved
cue while keeping the case ID/query fixed: usable+comfort, usable+celebrate,
unusable+comfort. Delete only the owned preceding item via the API between
conditions. Record writes, reads, deletes, selected hashes/acts and executable
verdicts. Malformed, wrong-case, unsupported-act and unknown-hash cues must refuse
selection. No renderer is needed for this engineering control.

Record actual UTC and monotonic sequence boundaries, returned memory content,
catalogue selection, execution, mapped intent, register/send, closed-file
receipt, database identity and a persistent random database token before and
after the renderer. Fixed envelope timestamps are not evidence of chronology.
Use an independently implemented Python audit of raw records, HTTP statuses,
hash bindings, same-database tokens and phase order, plus rejection controls for
reordered phases, a route/code mismatch, a changed database and missing cases.
Preserve all failed attempts and partial cases; no post-hoc exclusion.

## Operational limits

Mac only; one research process, one renderer, no workers or concurrent model,
browser or P3 jobs. Set DOTNET_PROCESSOR_COUNT=2; disable build-server reuse.
Sample resources at most every two seconds. Stop the entire batch at 1200 s,
owned RSS above 2 GiB for 30 s, available host memory below 3 GiB for 30 s, or
swap growth above 1 GiB for 30 s. Unexpected process exit, missing closure,
provider request, changed inputs/binaries/source also stops the batch. A waiting
tool is not a failed job and must not trigger a duplicate run.

On stop, terminate only owned process groups; retain telemetry/logs and completed,
in-flight and unattempted case accounting. Record the exact owned test-database
leases and clean only those leases if normal disposal could not complete.
Do not restart, relax limits or split the live prefix/suffix across databases
without a separately committed prospective amendment.

## Freeze, archive and acceptance boundary

Commit/push this plan before implementation, then freeze clean implementation
and binary hashes before the one measured attempt. Run targeted routing,
authority, prior replay-compatibility and repository tests. Archive a new packet
under a separate directory; do not rewrite the old packet, old manifest, failed
attempts or numerical facts. Audit raw archive completeness and negative controls.
Only actual passing evidence may change the first-round qualification flag.

Even a pass means finite, known-case operational dataflow qualification only.
C1 comparison, a newly frozen held-out batch, semantic adequacy, new P2 model
judgments, independent human review, formal Mac qualification, publication and
CAS journal eligibility remain separate open gates. Semantic interpretations
are AI-assisted. No email, submission, release or DOI deposit is performed.
