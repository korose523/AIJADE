# Next-stage proposal: bounded visible inputs, complete execution oracle

Status: **PROPOSED / NOT IMPLEMENTED / NOT RUN**. This is a consequence of the complete offline measurement, not a retrospectively selected primary design. Task/domain author decisions, primary development/selection split, N/q/T and device qualification remain pending. A separate plan commit must freeze the exact implementation, manifests and limits before the next measurement or model call; no supervisor receipt is inferred.

## Observed reason to change the prompt policy

The full-input profile contains every retained test input. At context 8,192 with a 1,024-token reply reserve, only 5/422 reference-probe tasks and 286/422 empty-probe tasks fit generation and both A/B templates for both models. At 4,096 with no reply reserve, the corresponding counts are 0 and 170. The maximum Qwen empty-candidate A prompt is 93,195 tokens. The reference ports include a shared semantic runtime and are capacity probes, not an estimate of future generated-code lengths. Reducing candidate code alone cannot remove the input-payload problem.

## Proposed offline comparison

Retain the original full-input measurements as the baseline. Implement a second, explicitly named exposure policy while preserving the exact manifest-bound bank, all 115,185 oracle cases, reference outputs, comparison rules and case identities.

1. Serialize **inputs only** using the existing canonical JavaScript value transport. Never inspect expected values, oracle success, model responses or difficulty scores to choose examples. Preserve the bank's fixed case order.
2. Consider at most three visible examples. Evaluate cases in source order. Tentatively append a case only if its input representation is at most 512 tokens under **both** exact local tokenizers and the complete empty-candidate A and B prompts, for both models, leave the declared candidate envelope and verification reply reserve. Record every considered/selected/skipped original case index and reason. Use one shared selection per task/scenario across model and A/B conditions. The actual whole-prompt check accounts for boundary effects; token lengths are not assumed additive.
3. Evaluate two engineering scenarios separately: context 4,096 / candidate envelope 2,048 / verification reply reserve 256, and context 8,192 / candidate envelope 4,096 / verification reply reserve 256. These are proposals for capacity comparison, not selected primary settings. A bounded visible-input policy may retain zero examples; report that explicitly and leave its inclusion decision pending rather than silently excluding the task.
4. Rebuild actual raw and chat prompts for every proposed task, both templates and both reference/empty probes. Repeat all tokenizer controls and complete independent-ID/byte checks. Recheck expected-output noninterference. Report coverage and input exposure separately from answer quality. Preserve non-fitting reference probes rather than trimming the shared runtime.

## Candidate and overflow rules before live pilots

An output-token cap is not a guarantee that extracted code will fit a verifier's differently formatted request. Before any live request, count the **actual complete** single-user chat prompt with that model's tokenizer and its declared reply reserve. If it does not fit, record `CONTEXT_OVERFLOW` with original candidate and counts, issue no request, and do not turn the event into a false verifier verdict or silently truncate code, cases or history. Preserve overflow/format/timeout counts in the full planned denominator. The final analysis must specify how these missing verdicts affect its estimand before the primary run.

The proposed generation cap is the scenario's candidate envelope. A 256-token verification reply budget also needs a finite format check; if it truncates required responses, stop and amend the budget before a new full pilot. Select a viable context only from resource/format qualification, not from favorable verifier errors. Retain any stopped or non-fitting scenario.

## Remaining design and author decisions

- Confirm task/domain adaptations, zero-visible-example handling and the development/selection partition before difficulty screening or primary generation.
- Freeze a live Mac admission and cold/warm prefill plan at each viable prompt/context setting. Offline vocabulary RSS is not model inference memory, and the earlier 44-task timing scenario does not budget this new pool.
- Use separate development, selection and precision-pilot tasks. Determine N/q/T, target uncertainty, candidate diversity and the within-task dependence analysis prospectively; do not choose the primary task set from main-study error rates.
- Compare stronger code-judge prompts as a separately specified baseline if within scope. CodeJudge and prior self-verification work already evaluate judgments against correctness; the intended scientific claim concerns error structure and admission composition, not a new correctness oracle.

No part of this proposal authorizes external compute spending, changes the complete oracle, supplies a new model-reliability result, or establishes journal eligibility or submission approval.
