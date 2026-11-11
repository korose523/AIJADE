# Paired known-case development comparator

The independently pushed protocol/layout/scoring commit is `290439f`; measured
source is `82f223b`. C1 retains real admission, execution failure/unknown refusal,
all three promotion gates, idempotency and revocation. C2 adds execution/receipt
joins and the shared promotion/state/outbox transaction. Neither is an externally
authored architecture. The adapters have no case-specific decision branches;
development identifiers expose case names, so label blinding is not claimed.

Twenty original case/arm databases remain alive from actual retrieved-cue
selection/execution through the shared later-started Godot session and the
admission/state/write-back/reuse suffix. Ten common rendered intents and the
exact sealed receipt events are shared across arms, not independent replicates.
The frozen order has five C1-first and five C2-first pairs. No model is queried.

The initial independent audit used an incorrect direct equality between diagnostic
DTO and wire proposals. Correction plan `831a321` was pushed before the audit-only
conversion at `87a6dd0`: numeric enum to wire name, exactly null optional fields
omitted, all other values retained and compared. Four fail-closed conversion
controls pass. Both audit attempts and before/after preservation hashes are
retained; original data, 71 binaries, C# apparatus and frozen scoring are unchanged.
No primary measurement was rerun. This is a post-measurement audit correction,
not a claim that the corrected audit was preregistered before the data.

Scores use seven scheduled invalid-promotion windows and eight scheduled
integrity-invalid reuse windows per arm. I3's first legal actions are allowed;
I7's legal promotion before revocation is not misclassified. Actual downstream
availability and transient service success are separate from persisted rows.
I8's failed state write leaves a committed spec/report under C1 and rolls them
back under C2. I6 is a claim/receipt contract mismatch; no visible-pixel evidence
or scope escalation is inferred. S1's semantic limit remains, and round-2
semantic action correctness is NOT_MEASURED because reuse renders no act.

Run `python3 experiments/ch7/paired-development-2026-11-12/verify_archive.py`.
The archive verifier checks every byte, lossless logical file, actual input
parity/chronology/database continuity, both parameter-hash conventions, full
per-case scores and seven disposable corruptions. It also retains the first
local default-regression QQ-observation timeout, five isolated passes and the
unchanged-default full repeat; its root cause remains unestablished. No timeout
was relaxed and the research measurement was not started before the checks.

The per-vertex skinning trace is unused in decisions and retained locally with
its hash; the licensed model is not redistributed. Old evidence/facts remain
unchanged. These are purposive known development cases, not a held-out comparison,
statistical superiority, general system validity, independent human judgment or
formal Mac eligibility. Formal held-out protocol/case-count approval remains open.
