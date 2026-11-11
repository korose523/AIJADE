# P2 whole-task judgment, matched exposure and constructed development calibration

This plan is committed and pushed on its own before its implementation and observations. It follows the accepted bounded-input preparation archived at `8c16b9d`. The scope is a versioned apparatus correction, a common input rule for the original 44-task bench and the 422-task public proposal, and a small constructed development calibration. It does not approve either task pool for a primary study, qualify the Mac, choose primary N/q/T, or replace any historical result. No supervisor receipt or external registration is inferred.

## Judgment target and compatibility

The bounded-v1 notice says to judge the full specification, while the historical A/B questions emphasize the listed examples. Preserve the historical two/three-argument builders, v1 profiles/policies, defaults, fingerprints and archived raw prompt bytes. Add an explicit `whole-task-v2` instruction version. Both A and B use the **same literal criterion** in place of their respective listed-example question:

> Judge the complete stated task, including valid inputs not displayed here. PASS means the code satisfies the full specification; FAIL means it does not. Passing only the displayed examples is insufficient.

The visible-input notice, candidate bytes, input rows, task specification, template layout and response format otherwise remain fixed. Textual target alignment does not establish equivalent model interpretation. Operational truth remains success on all retained execution cases; it is not a proof of universal program correctness. V2 is chosen for the declared construct, never because its observed error count is lower.

Use a versioned exposure schema for the explicit instruction version. Extend the existing optional request-policy path to the original bench, binding the entire embedded `bench-data.json` bytes and full input identities. Preserve each original calling convention and complete oracle; do not turn the old tasks into public-contract tasks. The opt-in path uses the same balanced allocation routine in both pools. Unconfigured historical runs remain unchanged. Versioned request policies may declare model retention explicitly; calibration fixes `keep_alive=0` for both compared instruction versions. No new top-level CLI switch is required.

## Outcome-blind matched input preparation

Prepare both complete input-only catalogs: original 44 tasks and the unchanged 422-task public proposal. Fix the same visible indices across models, A/B and instruction versions, in original input order, at most three cases. Each displayed argument representation must have at most 512 raw tokens in both local models. Each actual empty-candidate prompt under both instruction versions/templates/models must leave a 4,096-token candidate allowance plus 256 verification reply tokens in an 8,192-token context. Preserve zero-visible tasks and every decision. Formatting uses each original builder's actual argument representation, including the original bench's JSON.stringify behavior; keep raw argument identities separately. Select without expected outputs, reference code or model verdicts. Expected-output replacement must leave choices and prompts unchanged. Hash-check both full banks before/after; do not trim their execution tests.

Verify every selection-query count with the native and independent tokenizer implementations, and retain complete input and token records. This stage measures the planning prompts, not arbitrary future candidates. Every actual live request still receives the existing exact request guard. Keep the two original banks separate and retain every original task's identity and calling rule. Matched exposure cannot by itself isolate a population effect between these heterogeneous task sets.

## Fixed constructed controls

Choose the first original task in its embedded source order having more than three tests and at least four distinct displayed argument representations. Choose the first public task in manifest order, HumanEval/0; require the same minimum input diversity. These are known development controls, not held-out tasks or a representative sample. Record the eligibility screen of the old catalog. Fix choices before generating any model verdict.

Each task has two candidates: a positive reference and a deliberately limited lookup candidate. The old positive is its unchanged embedded reference. The public positive is this separately identified diagnostic implementation, not a replacement of its frozen reference port:

```js
function solve(numbers, threshold) {
  for (let i = 0; i < numbers.length; i++)
    for (let j = i + 1; j < numbers.length; j++)
      if (Math.abs(numbers[i] - numbers[j]) < threshold) return true;
  return false;
}
```

After input selection, construct the limited candidate as a JSON.stringify(arguments)-keyed lookup returning the expected values for the displayed cases and throwing an error for other arguments. Its visible outputs are deliberately encoded in the candidate. This is an overfitting control, not a leakage-free generation experiment. Before model calls, both positive candidates must pass the complete retained oracle; both limited candidates must pass all displayed cases and fail at least one undisplayed case. Retain all full/visible scores and construction bytes. If this construction rule fails, stop preparation and report it; do not choose another task after seeing model judgments.

## Paired local-model calibration

Planned observations: **2 tasks × 2 candidates × 2 templates × 2 instruction versions × 2 models = 32** verifier requests; four distinct candidates and two task units. Models are the existing exact Qwen2.5-Coder 7B and Llama 3.1 8B manifests. Fixed model block order is Qwen then Llama; within each model, shuffle candidate/template pairs with seed 20261111 and balance legacy/v2 first position across the eight pairs. No generation, training, model download, paid API, or primary regeneration is included.

Use temperature 0, seed 3759066737, context 8192, verifier reply cap 256, strict PASS/FAIL prefix parsing, no fallback, and `keep_alive=0` for each request. Use the actual guarded Ollama backend and real local counter, not a synthetic HTTP handler for these observations. Run one model and one request at a time on a dedicated local service. Save exact raw HTTP bodies/responses, model/runtime/binary identities, counter identities, prompt/candidate/input hashes, request order, timestamps, resource telemetry and all missing outcomes. Record prompt_eval_count and its difference from the independent offline count as a diagnostic, without assuming undocumented cache/BOS semantics or claiming live token equivalence from configured settings.

Require a fixed 60-second unloaded admission before each model: available RAM at least 7 GiB throughout, swap increase at most 256 MiB, and no loaded model in the owned service. Existing swap is recorded, not attributed to this work. Stop the entire attempt on a request timeout (180 s), counter/identity/format/length/transport failure, or a whole-calibration wall limit of 3600 s. Stop if owned-family RSS exceeds 9 GiB for 10 s, or available RAM stays below 1 GiB or swap rises more than 2 GiB from the initial unloaded baseline for 30 s. Record sampled resource semantics. Wait for the owned service to unload before the next request, with a 30-second unload deadline. Stop rather than extend limits or silently skip a cell. Wrong scientific verdicts are observations and do not trigger a stop. A stopped attempt retains completed, in-flight and unattempted denominators and has no accepted complete calibration summary. Never restart solely because a monitoring/tool observation times out; re-poll its confirmed process handle.

The dedicated service and all its children are the only inference processes that may be terminated or unloaded. Do not stop unrelated apps or other model services. Reuse existing cached models and working environments. Build-server cleanup, if used, is recorded before admission. Finite development observations do not replace formal device qualification or whole-run determinism.

## Analysis and reporting

Report every planned cell with full-oracle and displayed-case truth, parsed verdict, format/length state, latency, actual returned token metadata and missingness. Give finite confusion counts separately by model, template and instruction version, and paired verdict changes on identical candidates. Do not compute population error-rate confidence intervals, p-values, a winner, or a benchmark generalization claim from two tasks. Retain negative/null findings and any count/telemetry anomalies. Do not pool repeated prompts as independent samples. The original main estimates and all earlier preparation facts remain unchanged.

Update the journal and dissertation with a short evidence-bounded result chain and full records in supplementary material/the evidence archive. All interpretations remain AI-assisted. Author task/domain review, formal Mac qualification, development/selection split, difficulty/precision pilots, primary N/q/T, larger-model feasibility and official journal partition checks remain separate open gates. Publication means code/evidence GitHub commits only; no email, journal submission, GitHub Release or DOI deposition is authorized by this plan.
