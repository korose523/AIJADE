# P2-A reference input-order correction before a fresh execution

11 November 2026, Asia/Seoul. Original plan `c97638dec08db3a74d5ac6bd105f8ba5f7e5194c`; first execution code `c2400e4c3744f8a348f6c20b23bd3078c5b9a101`.

Both first-attempt passes attempted all 542 tasks, with 537 complete and five bounded incomplete task processes in each. Before any summary or oracle bank was accepted, the strict input validator rejected the raw records: the input transport's JSON serializer recursively sorted dictionary keys. That changes Python dictionary insertion order, which may affect a canonical function. The sorted problem fingerprint also failed to preserve this distinction. Typed dictionary records and the proposed bank writer used sorting as well. These are implementation/representation errors, not evidence that a task or model failed.

This amendment is committed and pushed separately before its repair. Preserve the entire first attempt, its fixed-limit failures, input mismatch and rejected analysis. Exclude every first-attempt row from the accepted preparation summary/bank; do not merge passes or task subsets.

Repair only order preservation: input transport and problem fingerprints retain the released dictionary order; typed dictionary item lists retain native order; the proposed bank preserves object insertion order in its serialized arguments. Keep strict record JSON and explicit nonfinite source input handling. Record metadata field ordering may still be canonicalized when it does not change data values/order. Add an artificial process fixture with an intentionally nonalphabetic input dictionary, and checks on transport, type records and bank JSON. Repeat the isolation/data qualification after the change.

Freeze and push the repaired source before rerunning both complete task orders from fresh output directories, using the same interpreter, 542 tasks, original compressed input hashes, two pass orders, seed, per-task CPU/wall/memory/output limits and total limit. The five first-attempt bounded failures remain visible; do not increase their budgets or change task selection after seeing them. This corrects source fidelity, not an outcome-based retry. Both attempts make no model calls.

Bind the new receipt to this amendment and its execution source commit. Continue to require strict input matching, complete-row validation, independent raw aggregation and lossless public-copy checks. Mechanical preparation, JavaScript porting, semantic test audit, device qualification and model-study completion remain separate.
