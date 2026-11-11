# Paired development: diagnostic DTO conversion correction

Post-measurement record, prospective only for the correction below. The complete
paired attempt at source `82f223b` has already finished. This file does not claim
that a corrected analysis was frozen before those data, and authorizes no new
measurement, case exclusion, model call or retry.

The original frozen scorer reconstructs the expected finite counts. The first
independent audit stops when comparing the promotion-job diagnostic DTO to the
wire-format proposal. Actual source `ShadowParamsProposal.ToJson()` maps enum
`ShadowParams=0` to `shadow_params`, `Evidence=1` to `evidence`, and omits optional
fields only when null. The DTO uses the numeric enum and explicit nulls. The
audit incorrectly required these two representations to be the same dictionary.
Its original failure log is retained. This is an observation-schema error, not
an observed condition difference or a failed primary case.

Before changing the audit, preserve hashes of every measured/derived output file
outside the copied renderer source. Implement only an explicit closed conversion:
require all diagnostic fields, reject unknown fields/enum values, map the enum,
omit exactly null optional fields, retain every non-null value, and compare the
whole converted object to the observed wire proposal. Test that normalization
preserves inputs and still rejects changed hashes, parameters, enum and unknown
fields. Do not delete or ignore the anchor or other substantive fields.

Keep the original protocol/layout/scoring contract, score code, C# apparatus,
binaries, inputs, outcomes, service observations, database snapshots and counts
unchanged. Re-audit the existing complete batch without rerunning it; verify all
preserved hashes afterwards. Archive both the original diagnostic failure and
the corrected audit/code/tests, state their chronology in the paper, and keep
the evidence scope as known development qualification. No held-out inference,
independent human review or formal approval follows from this correction.
