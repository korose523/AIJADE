# P2-A request-guard receipt and managed-memory correction

This amendment follows the complete bounded-input preparation executed at `37d4b3b3f3a3dbdd4ad9259435348b59025d03dd` under the earlier plan `9036bce`. It is fixed and pushed separately before correction and before a fresh complete attempt. No model completions were requested. This is an engineering correction, not a retrospective primary statistical analysis plan.

## Observed failed attempt

Retain `attempt-01` in full. Both 8,581-row complete tokenizer workers and the input-only selection finished, but the overall stage failed. The 4k Qwen guard control exceeded the unchanged 2 GiB sampled process-family RSS ceiling (2,170,793,984 bytes); other guard controls exposed an uncaught `InvalidDataException` from a counter-identity mismatch. The normal mock CLI used its historical default `pCorrect=0.5`; a newly written control incorrectly expected every execution to pass. Its 27/48 executions are synthetic outcomes, not model measurements or evidence of a failed reference port. Do not promote any prefix or individual substage into the accepted complete preparation.

## Fixed correction

1. Map an `InvalidDataException` from the exact counter to `COUNTER_ERROR`, retaining the raw request, a null verdict, the outstanding denominator, and the incomplete-run receipt. Add a regression control. Keep the identity mismatch and malformed counter fixtures.
2. For these bounded preparation subprocesses, configure `DOTNET_GCHeapHardLimit=0x30000000` (768 MiB managed heap). This makes collection pressure explicit within the existing 2 GiB process-family ceiling; it does not raise that ceiling or change CPU, wall or file limits. Record the environment, effective GC configuration and total memory available to the GC in the policy-probe summaries. Microsoft's documented environment value is hexadecimal: <https://learn.microsoft.com/en-us/dotnet/core/runtime-config/garbage-collector#heap-limit>.
3. Set `--p-correct 1` explicitly for the normal reference-backed mock and continuation controls, as required by their all-executions-pass assertion. Record that setting. Historical CLI defaults and model experiments remain unchanged.

After the correction is frozen, repeat the complete legacy-export, input-only selection, both models' controls and complete token streams, all four 18-case guard controls, and both normal mock/resume/identity-control groups in a new attempt directory. Keep the original input order, three-example/512-token rule, 4k/8k scenarios, references, full oracle, output caps and selection semantics unchanged. Verify the accepted profiles and raw prompt bytes against the failed attempt, but do not merge attempts.

The author task/domain review, development split, live inference/device qualification, difficulty/precision pilots, and primary N/q/T selection remain open. Synthetic transport controls and tokenizer arithmetic add no model-verifier reliability observations.
