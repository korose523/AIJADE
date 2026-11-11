# Chapter 7 staged research adapter: development qualification only

Date: 2026-11-12 (Asia/Seoul). Base: `c02fb7f87a8e5041580e77181655c6d7f85f4baf`.

Status at registration: implementation NOT_WRITTEN, development qualification NOT_RUN,
held-out C1/C2 comparison NOT_RUN. This is a prospective engineering and finite-case
qualification protocol, not a supervisor approval, formal hardware qualification,
independent review, or registration of the later held-out comparison. The current
author request authorizes continued reversible project and manuscript development
on the Mac. No model request, training, cloud compute, user data, deployment, or
message to another person is included.

## Question and boundaries

The dissertation's Section 7.3 still lacks a component that turns an admitted
proposal into a promotion job and one authority for a skill's evidence state.
Build these in an isolated Git worktree. Qualify the C2 path on the ten declared
development cases below. These cases are never reused as held-out cases. Do not
populate Table 7.3 or claim a C1/C2 comparison from this batch. The later C1
configuration, case counts/order and scoring must be fixed separately, after this
qualification and before any held-out cases are written, as required by the
supervisor. Implementation inspection and all semantic judgments in this batch
are AI-assisted, with no independent human coding or author approval inferred.

Use the existing separately implemented MOSAIC Godot client, headless, on a copy
outside the MOSAIC checkout. Only the `behavior_overlay_pre_solve` receipt stage is
available. This is a source of sealed parameter-application receipts, not an
observation of pixels, later physics, semantic appropriateness, or independent
replication. No connectome research is imported into this study. Choose Godot for
this development implementation; final dissertation protocol approval is open.

Preserve all earlier P1/P2/P3 evidence and the product's frozen memory files.
P1-A, P1-B and P1-C are already archived. Any extension to the promotion service
must preserve its existing entry point and all three gates, and be checked by the
Chapter 4 regression. The production server must not register or call the new
research adapter or its skill authority. Research code with cross-module product
references lives in the existing tests host, not a research module with forbidden
project references.

## Artifacts and authority

The pure research records distinguish Unknown, Failed, Verified and Revoked, and
bind skill ID, code SHA-256, task/bench identity, execution ID, intent ID, session,
asset version, receipt stage and scope. A single PostgreSQL research table owns
the current state and revision; outcome memories are projections and cannot
restore a revoked state. Unknown is never converted to Verified by a self-verdict
or absent execution. The mapper accepts only named dialogue acts from an explicit
allow-list and never executes arbitrary fields returned by a skill. The mapping
version and packet values are archived before dispatch.

Before rendering, run the exact archived candidate in the existing deterministic
Jint sandbox. Select a usable archived program and an unusable verifier-passed
program whose classification remains unchanged by the AI-assisted re-tally of
Section 5.6.7; archive full source paths, line identities and hashes. The expected
negative program is the existing `parse-query-string` example that mishandles an
empty query, rather than a calling-convention or disputed-task failure. Selection
is purposive development, not a new model sample. No expected outputs are sent to
a language model.

Write the registry before sending the ten intents in one healthy renderer
session. Close the renderer, seal the file with the existing importer and
recompute its checks before importing request/receipt pairs through the actual
event boundary. There is no action-time guarantee. Case-specific databases have
one synthetic user and the same registered session; no production database is
used. Retain the initial memory write, actual retrieval, execution record,
registered intent, emitted UDP packets, sealed receipt, admission result,
promotion job and gates, database snapshots, outcome write and round-2 retrieval
for every case. No ledger row is a substitute for exercising the actual path.

The adapter constructs its promotion job only from a successfully admitted
proposal and the round's qualified evidence. A caller-owned PostgreSQL transaction
joins the promotion service's existing spec/report writes to the skill-state
revision and a research outcome outbox. Failure of any write rolls all those
writes back. The outbox then submits the outcome through the authenticated
`/api/v1/v9/perception` endpoint; it records acceptance, refusal or unknown and
does not bypass the product's policy. It does not pretend the later HTTP memory
write is part of the database transaction. Re-delivery uses the same event ID;
only a successfully retrieved, identity-consistent outcome can enable round-2
reuse. Missing/refused memory leaves reuse blocked. Revocation always wins over
an older retrieved memory.

## Expected development cases, fixed before implementation

All cases use valid schemas, the same available fields and the actual local
oracles. Refusal reasons may include several earlier checks; report the observed
first stop and complete path rather than force a later check to execute.

| ID | Intervention | Required C2 qualification behavior |
|---|---|---|
| H | Usable archived candidate, matching execution/intent/asset, actual applied-stage receipt | One promotion; Verified with explicit test/stage scope; outcome accepted and retrieved; one round-2 execution |
| I1 | Borrow another registered intent's otherwise valid execution receipt | Refuse cross-intent binding; no promotion; no round-2 execution |
| I2 | Proposal asset version differs from actual receipt | Refuse version mismatch through the local admission and/or cross-record check; no promotion or reuse |
| I3 | Deliver exactly the same admitted outcome twice | At most one spec, one report, one authority revision for the outcome and one outcome-memory event; round-2 executes at most once |
| I4 | Execution evidence absent, self-verdict available | Persist Unknown with reason and scope; no promotion or reuse |
| I5 | Verifier-passed archived program fails the unchanged execution oracle | Persist Failed and refuse promotion; no reuse; retain actual failing case |
| I6 | Claim a later stage than `behavior_overlay_pre_solve` | Refuse stage escalation; no promotion or reuse |
| I7 | Revoke after a valid first round, then retrieve its older positive outcome | Keep Revoked at the authority; no round-2 execution despite retrieved positive memory |
| I8 | Actual database trigger raises on authority write after spec/report insertion | Roll back spec, report, authority revision and outbox together; no outcome or reuse; retain PostgreSQL error code |
| S1 | Correct identifiers and test-passing code, but choose an allowed render act inconsistent with the declared requested act | Identifier/stage/test checks accept; round-2 reuse remains possible; report this semantic counterexample as an admitted limit, not a detected fault |

Each invariant has one development example only; H/I3/I7 establish separate
normal starting paths but are not independent samples of healthy behavior. S1's
declared content mismatch is constructed and AI-assisted, not human-validated
emotion quality. The ten cases provide finite qualification counts only. No
confidence interval, statistical superiority or real-user failure rate is
estimated. An unmet expected result is a qualification failure, retained with its
logs. Any correction is described and followed by a complete fresh batch; batches
are not spliced and failed attempts are not overwritten.

## Resource and stop rules

One research process family at a time, .NET worker ceiling 2, one renderer, no
model loads, no browser batch or P3 full-corpus job. Existing synthetic PostgreSQL
container may be reused; each owned test database is dropped at teardown. Do not
stop unrelated applications. Before execution record tool versions, code/plan
commits, selected candidate/input hashes and frozen binary hashes. Input source
hashes are checked again after execution.

Use a monitored controller with wall limit 1,200 s, owned process-family RSS limit
2 GiB sustained for 30 s, available-memory floor 3 GiB sustained for 30 s, and
host swap increase above start of 1 GiB sustained for 30 s. Sample at <=2 s.
Unexpected exit, timeout, unresolved seal, unavailable dependency, exceeded bound,
or attempted model/provider request stops the batch. A new complete attempt
after a software repair needs a dated deviation record and a fresh output
directory; resource stops are reported, not worked around by lowering limits.
Keep every attempted and unattempted case explicit. These bounds govern the
development measurement; they do not establish formal Mac hardware eligibility.

## Verification and publication

Before merging: reproduce the existing Chapter 4 contract/admission/promotion
regression without overwriting archived outputs; run new meaningful atomicity,
idempotency, stale-state and mapping controls; run the default repository suite
and scope checks. Reconstruct finite qualification counts independently from raw
database/HTTP/case ledgers with a separate Python verifier, including rejection
controls for a missing case, changed raw hash and an impossible positive reuse.
Archive program/plan/input/binary hashes, raw logs, telemetry, failed attempts,
complete result rows, limitations and a manifest. Freeze the implementation
commit before the measured development batch, then publish the raw evidence in a
separate commit. Merge only after qualification and regression are archived.

Update the dissertation's Table 7.2 and implementation description with actual
observations; leave Table 7.3 empty. Where the P1 journal manuscript says no
adapter exists, distinguish the historical P1 apparatus and the new research-only
prototype. Do not turn this qualification into a new P1 causal claim, independent
external comparison, held-out result, product automatic-learning path, or journal
readiness. All old numerical facts remain immutable; any new qualification facts
use a separate namespace and retain failed-attempt facts.

The later held-out study, P2 main model generation and formal Mac qualification
remain open. This plan is pushed as a separate commit before implementation; no
supervisor email or formal approval is implied by that push.
