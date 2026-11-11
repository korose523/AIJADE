# Chapter 7 qualification observer correction

Date: 2026-11-12 (Asia/Seoul). Original plan: `aed0795`.
First measured implementation: `080409a9f6d50ef1c860ed35fb0c8ba1474ed2ea`.

The first complete development batch ran all ten cases, without a resource stop
or model request. Its aggregate status is STOPPED because one qualification
assertion failed. I2 returned HTTP 400, wrote no promotion and blocked reuse, but
the observer incorrectly expected the private `asset_version_hash_mismatch`
reason to appear in the HTTP response. The existing endpoint deliberately emits
the generic `INVALID_RENDER_TRACE_REFERENCE` message. Nine other cases met their
declared outcomes, including the intentionally admitted semantic counterexample.
No result from this batch is presented as a completed qualification, and no row
will be spliced into a later batch. All first-attempt records are retained.

Before the next complete attempt, correct only the observer: require HTTP 400
with the existing public error code, then invoke the unchanged event service on
the identical refused envelope as a diagnostic and capture its typed refusal
reason. Require `asset_version_hash_mismatch` from that diagnostic and verify
that the refused event remains absent. The diagnostic is an additional attempted
append for I2 and is reported as such; it must write zero events. No production
error message, admission rule, promotion gate, resource limit or expected
behavior is relaxed. Also archive the actual persisted spec/report JSON in the
database snapshots, supplementing the existing counts and returned job/gate
records.

Commit and push the corrected observer before rebuilding from the clean commit.
Repeat all ten cases, registrations, renderer receipts, fresh case databases,
actual memory writes and second-round retrievals in a new output directory.
Run the Chapter 4 and new authority regression again. These remain development
data. The held-out C1/C2 study is still NOT_RUN, as are the formally gated P2
model runs and Mac hardware qualification. This amendment is not a supervisor
approval or a new model-calibration authorization.
