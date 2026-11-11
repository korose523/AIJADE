# Chapter 7: strong local baseline and paired development scoring

Prospective development protocol, after the retrieval-led packet at public
`c460f89de3d3796b38a660f52c75712d71b27022`. Commit and push this file, the
machine-readable scoring contract and balanced layout before implementation.
This is not a held-out protocol, supervisor approval or external registration.
No new cases, model judgments, training, real-user data or journal submission.

## Question and treatment boundary

On the ten already-known development cases, can a module-local implementation
and the added cross-module constraints be executed with identical available
inputs, and can complete records distinguish durable contract-invalid promotions
and integrity-invalid reuse from local decisions, partial writes and unknowns?
The comparison qualifies apparatus and scoring. Cases are purposively constructed,
share programs/renderer context and are not independent population replicates.
Report finite counts, without a population rate, CI, significance claim, general
design superiority or independent-author validation.

C1 is `strong-local-v1`, an author/AI-implemented baseline, not an external system.
C2 is `cross-module-v1`. Both use exactly the same actual perception/memory APIs,
closed render file, importer, candidate programs, benchmark, mapper and inputs.
Both retain all of the following:

* Strict HTTP event contracts, actual render identity/hash/version admission,
  closed-file/seal/hash/stage checks in the renderer importer.
* Re-reading the actual admitted proposal and matching its ID, session, input
  hash, parameters and render reference to the job's proposal.
* Candidate identity/hash shape checks and fresh execution: failed, missing or
  incomplete execution cannot qualify merely because its self-verdict is pass.
* The unchanged integrity, evidence and PGC gates of `PromotionService`.
* Outcome replay identity, a per-skill advisory lock, locally atomic skill
  authority/outcome/outbox, revision checks, revocation and at-most-once reuse.
  Both read the same current authority before reusing a retrieved memory.

C2 additionally checks execution intent against receipt intent, execution/receipt
asset versions and claimed versus actual receipt stage. C2 also puts the existing
promotion spec/report writes in the authority/outcome/outbox transaction. C1
lets the unchanged promotion service own its spec/report transaction, then commits
the local authority/outcome/outbox transaction. These are the only treatment
differences. C1 cannot skip normal execution, admission, idempotency or revocation
checks to manufacture an apparent advantage for C2. No production registration
or configurable product bypass is introduced; default research behavior stays C2.

I2 can be stopped by common HTTP checks, I3 by common deduplication, I4/I5 by
common execution checks, and I7 by common revocation. Equal outcomes are retained.
I6 is a claim/receipt contract mismatch: a promotion that accepts that evidence
violates the declared contract even if its stored scope remains the actual
overlay stage. Do not claim it grants visible-pixel evidence or proves a display.

## Paired execution

Freeze the two unchanged historical programs/selection, benchmark and mapper
from `experiments/ch7/2026-11-12/selection.json`. Initial cues contain only case,
task, program fingerprint and requested act, not outcome labels. Preserve all
H/I1–I8/S1 interventions and the explicit missing-execution and semantic controls.
Neither adapter receives a case label or expected answer as a decision input.

Use one .NET process, twenty fresh owned case/condition databases, no workers,
and one shared Godot session. Both arms actually write/read/parse each route and
independently execute the selected candidate (except I4). Hold all twenty original
databases and their continuity tokens until their suffixes complete. Verify both
arms' returned cues, selected program/task, execution result apart from duration,
and mapped intent are identical. Start Godot only after all prefixes complete.
Register/send each of the ten common intents once. Both arms import the exact
same sealed request/receipt events and receive the same I1/I2/I6 interventions.
There are ten shared rendered intents, not twenty independent render replicates.

The committed JSON layout uses seed 20261112, a shuffled order of the known ten
pairs, and exactly five C1-first/five C2-first pairs. Follow it for prefix and
suffix execution. Databases are independent fresh instances, with no carryover
between arms; the shared external file removes render-session variation from the
treatment. Source/code/benchmark/model/clip/plan/binary identities, actual UTC and
monotonic phases, SQL state/error and complete HTTP requests/responses are retained.
Logical envelope timestamps are not wall-clock evidence.

I8 injects the same authority-write failure in both arms after checking that
one spec and one report are visible. Record the actual promotion-service call
and its return separately from the final committed database rows. A transient
`Ok=true` before outer rollback is not a durable promotion. In C1 the promotion
may already be committed when the later local state write fails; report the
persisted rows and absent state/outbox, without reporting a successful outcome.
No automatic recovery/retry is added. I3 repeats commit, delivery and reuse;
I7 revokes after delivery and before second-round retrieval in both arms.

## Fixed scoring contract

The JSON scoring contract defines event windows and allowances before execution.
Counts are reconstructed from persisted spec/report JSON, current authority,
actual outcome delivery/read and sandbox-execution records, not qualification
flags or the promotion service's transient return.

There are **seven scheduled invalid-promotion opportunities per arm**:
I1/I2/I4/I5/I6, I3's duplicate commit and I8's injected state-write failure.
I7's first promotion precedes revocation and is not an invalid-promotion
opportunity. I3's first legal promotion is allowed and excluded from its duplicate
error. Each declared invalid opportunity contributes zero/one if any forbidden
durable promotion persists; also retain raw row counts and any extra rows/errors.

There are **eight scheduled integrity-invalid reuse opportunities per arm**:
I1/I2/I4/I5/I6/I7/I8 and I3's duplicate reuse. I3's first legal sandbox reuse is
allowed. Earlier refusal or an absent outcome does not remove the scheduled
opportunity from the denominator. Separately report actual query count,
retrieved-memory availability, promotion-service entry (including invocation
number) and executed reuse at each window. Conditional availability counts must
not replace the fixed denominator or be read as comparable causal rates.

H supplies normal acceptance/refusal/unknown accounting. S1 supplies a deliberately
wrong allowed act with valid identities/execution. Report its associated promotion
and sandbox reuse separately from integrity violations. **Round 2 renders no act
and generates no model answer**, so semantic correctness of a second-round act
is NOT_MEASURED, rather than zero errors or a repeated wrong act. No emotion or
answer-quality labels are inferred from identifier checks or code execution.

Expected development traces, not outcomes to assume: C1 may persist seven specs
and execute five second-round sandboxes, versus C2's four and three. C1's known
contract-invalid persisted promotions are I1/I6/I8 and integrity-invalid reuse
I1/I6; C2 is expected to stop these. I8 has absent authority/outbox in both arms;
the expected final spec/report counts differ. Equal I2/I3/I4/I5/I7 controls and
the admitted S1 limit must remain visible. An unexpected trace stops qualification
and is retained; do not tune the baseline, discard a case or relabel a window
after seeing it. These expected traces demonstrate finite designed mechanisms,
not newly discovered population effects.

## Qualification, resource limits and archiving

Before the measured batch, run actual-database controls for common admission,
execution, idempotency/revocation, both transaction modes and the cross-record
contrast, plus existing P1/default regressions and old C2 replay compatibility.
Freeze/push clean implementation and binary hashes before exactly one complete
paired known-case attempt. No held-out case is written or inspected in this step.

Use DOTNET_PROCESSOR_COUNT=2 and disable build-server reuse. One research process
plus one renderer, no simultaneous model/browser/P3 jobs. Sample at most every
two seconds; stop at 1200 s, owned RSS >2 GiB for 30 s, available memory <3 GiB
for 30 s, or swap growth >1 GiB for 30 s. Unexpected exit, provider request,
changed inputs, missing client closure or input/arm mismatch stops the whole
batch. Keep failed, completed, in-flight and unattempted rows. Clean only recorded
exact owned database leases/process groups. An observation timeout is not a stop
or permission to restart. Any correction/retry requires a new prospective record.

Independent Python reconstruction must validate both full arms, the shared-input
parity, before/after database tokens, render seal and both applied-parameter hash
conventions, actual phase/dispatch order, transient versus durable promotion,
per-case scoring windows and fixed denominators. Reject disposable corruptions:
missing arm/case, route/code mismatch, unequal inputs, changed database, corrupted
render file, hidden partial-promotion rows and changed denominators. Preserve all
attempts and the old packets/facts. Add new results under a separate directory
and fact namespace. The per-vertex skinning trace remains local with a hash and
is unused in all decisions; do not redistribute the licensed model.

After this development qualification, freeze both checks, mapper/state policy,
adapter and scoring version before drafting any genuinely new held-out batch.
Formal held-out protocol/case-count approval remains open. New held-out results,
formal Mac qualification, P2 model judgments, P3 answer quality, author/supervisor
approval and CAS journal eligibility are not established by this protocol.
