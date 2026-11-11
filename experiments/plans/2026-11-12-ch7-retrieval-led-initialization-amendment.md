# Retrieval-led development: database-initialization amendment

Prospective amendment, after retained attempt development-01 at source
`4c549bf27889492d125b16c0f0bb1b40e0e32075` and before the correction/new run.

That attempt stopped during H's database-token initialization: SQLSTATE 42601,
"cannot insert multiple commands into a prepared statement". The test combined
CREATE TABLE and a parameterized INSERT in one prepared command. H had no route
write/read, candidate execution, mapping or rendering; the nine remaining cases
were not reached. No renderer or model was started, no case was completed, and
the single exact owned database lease was disposed and independently found absent.
The original receipt/logs/XML/telemetry and incomplete journal remain unchanged.
Its receipt uses "in-flight" for any started case lacking a completed row; the
ledger classifies H as failed initialization rather than an active running case.
The flow's exitCode was not filled by the controller's early-exit branch; XML and
process exit establish failure, and the controller must record that branch too.

Split token table creation and parameterized insertion into separate calls.
Exercise this same initialization in the ordinary actual memory-API routing
control, checking its database token before and after cue mutations. Do not alter
candidate code, tasks, routing cues, expected results, stage/hash rules, authority
gates, semantic control or resource limits. Preserve old replay compatibility.

After targeted/default checks and a clean source/binary freeze, authorize exactly
one fresh complete development-02 attempt with new owned databases and a new
renderer session. No prefix from the failed attempt may be reused. Record both
attempts in the new archive, audit the failure's complete accounting, and accept
only separately passing development-02 raw evidence. Any further operational
change/retry needs another prospective record. No C1, held-out or model experiment
is added by this amendment.
