# P2-A bounded visible inputs and request-budget preparation

11 November 2026 (Asia/Seoul). Continue from archive d43a10234121eb8551ef2b602d877c25fec0f911 and its fixed 422-task, 115,185-case proposal. The preceding complete tokenizer study found only 5 reference-probe and 286 empty-probe tasks jointly fitting both models' generation/A/B prompts at context 8,192 with reply reserve 1,024. This plan makes the preceding NEXT_STAGE proposal concrete before implementation. It is an offline engineering preparation, not a new task-eligibility decision, primary condition or reliability study. Author/domain review, zero-example eligibility, development/selection split, N/q/T and device qualification remain pending. No supervisor receipt or external registration is inferred.

## Fixed inputs, scenarios and selection

Keep the bank manifest 5592614a78d6e9ca0ecd19ab3684cbd455880aba7a0ecafe4689a73a19dab2bf, every statement/calling contract, all execution cases and comparison rules unchanged. Reuse the exact two local GGUF/model/template/system identities, native vocabulary-only helper and independent BPE implementation from the preceding study, including the uncleaned byte-piece decoder and 15 controls per model. Check the saved model-file identities and all native/library/extension/template hashes; a changed input blocks the attempt rather than substituting a new model. No inference context, training, /api/chat or /api/generate request is created in this preparation.

Compare both proposed scenarios exhaustively on the same tasks:

| Scenario | Context | Generation/candidate allowance | Verification reply reserve | Maximum visible cases | Maximum raw input tokens per case, in both models |
|---|---:|---:|---:|---:|---:|
| compact4k | 4,096 | 2,048 | 256 | 3 | 512 |
| compact8k | 8,192 | 4,096 | 256 | 3 | 512 |

Expose inputs through a C# input-only descriptor: original index, exact canonical JavaScript argument literal and its byte hash, task instruction and total case count. Do not expose expected outputs or reference implementations to the selector. Examine cases in bank order. After three accepted cases, label every remaining index MAX_VISIBLE_REACHED without using its outcome or length to change the selection. Before that, reject an input exceeding 512 raw/no-automatic-special tokens under either model as INPUT_TOKEN_LIMIT. Otherwise tentatively append it and build the actual empty-candidate A/B prompts through the normal C# builders. Accept only if, for both templates and both models,

    exact chat/completion input tokens + candidate allowance + verification reply reserve <= context

The empty placeholder remains in the measured prompt, so the additive candidate allowance is conservative, not a proof that arbitrary generated code fits. Record every considered, selected or skipped original index and the four model/template budget values used for the decision. Use one shared selection per task/scenario across models and A/B. Retain zero-selected tasks and reasons; no task is silently excluded. Case input lengths and tentative complete-prompt counts are independently checked against the native engine before accepting a selection archive. Deduplicate identical query bytes by SHA-256 while retaining every decision's query identity; never deduplicate task observations or change their denominator.

## Presentation boundary and unchanged execution

Add an explicitly named bounded exposure policy to the normal prompt builders. Keep original case indices in displayed labels. Both A/B receive the same notice that only the selected examples are visible, the complete oracle is withheld, and the judgment concerns the specification; a zero-example prompt says so explicitly. The historical full-input builder remains byte-identical. Because the bounded policy includes this notice, the original full-input profile is a descriptive capacity baseline, not a wording-matched causal control of reliability. Any later reliability comparison needs its own fixed, wording-matched design.

Never replace or truncate BenchTask.Tests. The execution sandbox always sees the original full task. Bind exposure records to the full bank identity, task/input hashes, model/template identities and scenario. A strict loader rejects missing/duplicate tasks, changed inputs, unsorted/duplicate/out-of-range indices, excess selections or mismatched scenario/model identities. A single opt-in request-policy file supplies the selected exposure, exact context, stage-specific reply caps and hash-bound local tokenizer adapter; no historical defaults change. Include policy/exposure identities in normal run fingerprints, step records and resume checks. Check mock continuation and reject a different policy before output creation.

## Actual-request overflow and recording

For a policy-enabled Ollama backend, count the actual whole single-user chat prompt before dispatch, including retries, prior code/critique and effective default system/template. Use a local vocabulary-only adapter with the native and independent engines and finite, bounded JSONL transport. Verify the adapter/model/template/library identities at startup. Always use the scenario's generation cap for generation/warm-up and its verification cap for verification. Do not assume counts are additive or that an output-token bound guarantees a later candidate fits.

Persist the unchanged raw prompt, its identity, chat identity, exact token counts/ID hashes, stage, reserve, context and fit decision before HTTP dispatch. For CONTEXT_OVERFLOW issue no HTTP chat request, retain the original candidate/prompt, leave verdict null and stop the entire attempt with a separate incomplete-run receipt. Record planned step slots and completed steps; do not write an accepted primary summary or turn the overflow into false rejection. Preserve completed responses and non-attempted slots. Counter, identity or transport failures also fail closed and retain an infrastructure status. A later primary plan must define missing-verdict treatment before any scientific run.

This preparation tests the real backend dispatch boundary using an isolated synthetic HTTP handler and the actual local tokenizer adapter; no real model response is requested. Both fitting and overflowing generation/verification/retry fixtures, malformed counter replies, changed identities and exact budget boundaries receive controls. Merely having a policy file is not treated as a working guard.

## Complete measurement, limits and acceptance

Freeze corrected source/binary/input identities before selection and full tokenization. Retain failures separately; any measurement-affecting correction is fixed before a fresh complete repeat. Use one native vocabulary process at a time. Each model's full offline family is limited to 1,200 CPU seconds, 1,800 wall seconds, 2 GiB sampled RSS and 512 MiB per physical output file. The input-only export/selection controller has 1,200 CPU seconds, 1,800 wall seconds and 2 GiB sampled RSS; a single prompt is limited to 1 MiB UTF-8. Lossless compression may reduce storage without relaxing physical limits. Any exhausted limit produces an incomplete attempt, not a smaller population.

Measure all five actual prompt kinds (generation, A/B with reference, A/B with empty candidate) for all 422 tasks in both scenarios and both models: 4,220 task/scenario prompt forms, 8,440 model/prompt rows and 33,760 raw/chat/special-token views. Preserve ID sequences and byte reconstruction, plus the exact input/tentative queries needed to audit every selection decision. Reference ports retain the shared runtime even when they do not fit. Do not trim them to improve coverage.

Independently recompute all selection decisions and joins, expected-output noninterference, full oracle identity, exposed/hidden counts, zero-example counts and actual per-stage context arithmetic. Compare with the original full-input profile only under the declared descriptive scope. Missing rows, changed templates, corrupted token IDs/hashes, altered selection indices and changed policy/bank identities must be rejected. Report all task/scenario outcomes, not only fitting tasks. No inferential p value or model-quality improvement is computed from these preparation records.

Publish the implementation and complete lean evidence, check the exact GitHub CI, then update the English/Chinese P2 materials, dissertation and review/evidence records. Keep detailed preparation in the journal supplement, with the main text stating only the constraint and remaining gates. Formal live Mac admission, response-format and difficulty/precision pilots require separately fixed plans; this step neither supplies them nor declares the study submission-ready.
