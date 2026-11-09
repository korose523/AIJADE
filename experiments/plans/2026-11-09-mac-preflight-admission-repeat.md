# Mac preflight: one repeat after an explicit memory admission check

Written after the first Qwen 7B attempt on 9 November 2026 and before any repeat. Development amendment under the author's current request, not a primary experiment, supervisor approval, public preregistration or a replacement of the initial result.

## Trigger already observed

In `experiments/mac-preflight/2026-11-09-7b8b/`, Qwen loaded and returned READY, then the first generation was stopped when system swap grew by more than 2 GiB relative to that model's starting snapshot for 30 seconds. The cold response alone supplies no representative generation time. The initial baseline had about 5.1 GiB available RAM; this is a descriptive observation, not a causal diagnosis of why swap grew. Preserve all of that attempt and complete the initially planned Llama attempt first.

## Fixed corrective condition and scope

After both initial attempts and model unloading, collect a 60-second admission trace with no model loaded. Admit one additional Qwen-to-Llama pass only if available system RAM is at least 7 GiB at every sample, used swap does not increase by more than 256 MiB from admission start at any sample, and the private listener reports no loaded model at the beginning and end. This reserve is an operational development criterion, not a guarantee against pressure. Do not terminate unrelated applications, flush caches, change OS settings, move model storage, or relax the original within-model bounds.

Use the original frozen `fixtures.json` byte for byte and the original `run_preflight.py`, exporter binary, model digests, request order and sampling settings. Record this amendment's hash separately in `admitted-repeat/execution-scope.json` before any repeated inference. The output root is a new `admitted-repeat/` subdirectory, without overwriting the initial result. Both models receive at most the same ten requests again; if either stops, there is no third attempt in this amendment. If admission fails, retain its trace and do not start a repeat.

The models remain explicitly unloaded before each READY request, but the OS file cache has already been used by the first pass. Report these conditions separately. A repeat that completes after a stopped first attempt establishes conditional execution of these prompts in that resource state; it does not erase the stop, show that memory pressure is impossible, or prove a causal benefit of the admission check. Retain absolute swap levels and changes from the first attempt's baseline as well as each model's immediate baseline. Existing swapped pages cannot be described as zero resource cost.

## Analysis and reporting fixed before repeat

Report every attempt in its original order. For a completed repeated request, retain raw response, token/duration fields, loaded context and model identity, and compare its verdict-format classification with the existing C# parser without using verdict correctness to select a model. Calculate a separate device-time scenario for each pass only where all required request classes completed. Use the three archived runs' actual call counts and clearly label the 30% planning allowance as an assumption. No statistical interval or worst-case time bound is inferred from one prompt per class. No P2 primary result, determinism series, larger-model study, hardware qualification or new participant work is authorized by this development amendment.
