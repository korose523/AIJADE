# Mac 7B/8B capacity and latency preflight

Date: 9 November 2026 (Asia/Seoul). Status: development preflight, explicitly authorized by the author's request in this chat. This is not the P2-R primary regeneration, the original Windows hardware qualification, or an external registration. No supervisor approval or external timestamp is inferred. The original P2-R plan remains unchanged.

## Fixed scope before model calls

Use the existing Mac, one model at a time, in this order: `qwen2.5-coder:7b-instruct`, then `llama3.1:8b`. Reuse the cached Qwen model without re-pulling it. Download Llama only if missing. Record exact digests and compare them with the archived control identities. Use a private local Ollama listener, one loaded model and one parallel request. Do not stop unrelated services, clear system caches, change drivers, or alter power settings.

Requests use `/api/chat`, `stream=false`, one user message, temperature 0, seed 3759066737, `num_ctx=4096`, `num_predict=4096`. Other sampling options stay at the model/server defaults as in the archived runner; save the model's parameters and template. A cold request means the model was explicitly unloaded; the operating system's file cache is not flushed. Warm requests retain the model with `keep_alive=300`.

Each model receives the same ten fixed requests:

1. The runner's `READY` warm-up, after unloading, to measure load time. Its content is discarded for research conclusions.
2. The longest initial-generation prompt among the existing 44 tasks, selected by character length with task-id tie breaking.
3. An informed-retry prompt constructed by the existing builder from the longest failed archived candidate program and its actual execution feedback. Its precise construction and provenance are frozen in the fixture file, not described as an exact historical full trajectory.
4. The longest verifier-template-A prompt over the non-reused candidates in the three archived controls.
5. Template B for the same candidate, retaining the information and changing only the established wording.
6. The five existing synthetic format-check tasks with template A, in their existing order. Only PASS/FAIL format is used for qualification; verdict accuracy does not select models.

The exporter calls the existing .NET prompt builders. Before model calls, freeze a fixture JSON containing the exact prompts, selection rules, source-file and archive hashes, and a SHA-256 of this plan and the exporter binary. No prompts, tasks, candidates or sampling settings are adjusted after seeing outputs. Record the actual source HEAD, dirty state and source hashes; a local file freeze is not a clean Git commit, prior public disclosure or preregistration.

## Measurements and bounded stops

For every request save the exact body and full response, endpoint version, model digest and loaded-model state. Measure wall time, load/prompt-evaluation/generation durations and token counts, completion reason, empty/truncated responses, and format. Report generation tokens/second separately from wall-time throughput and startup. A successful request using a 4096 allocation does not show that arbitrary 4096-token prompts and outputs are supported without truncation or context shifting.

Sample available RAM, used swap, and the resident memory of the owned server/runner processes every second. RSS includes shared mappings and is not exclusive physical model memory. Save baseline and peak values and swap increments. The initial system already uses swap; do not treat its absolute level as caused by this experiment.

Stop the model's preflight on any of: available RAM below 768 MiB continuously for 15 seconds; swap grows by more than 2 GiB relative to that model's preflight baseline continuously for 30 seconds; an OOM or unexplained runner crash; a request exceeds 900 seconds; the model's ten-request window exceeds 3600 seconds. These are development resource/time bounds, not tests of the primary experiment's one-hour timeout. Unfinished requests remain censored records, not zero-token successes. Unload the owned model after a stop; keep the request, reason and available error evidence. Do not retry with smaller context, output limits or quantization under the same condition. HTTP errors or malformed/incomplete replies are preserved, and any retry is a separately named deviation.

## Interpretation and subsequent work

Report capacity, protocol/format, and timing separately for each model and request class. No confidence interval for general throughput is claimed from this finite preflight. Budget later runs using counted generation, retry and verification calls from the archived logs and observed request-class times; label extrapolation and allow unmeasured longer replies. Do not multiply 7200 steps by a single token speed or reuse the Windows GPU timings.

The result may establish that these frozen requests complete, or identify pressure, timeout or format limits. It does not establish sustained hardware qualification, whole-run determinism, accuracy, the P2-A/B/R primary results, the full P3-C policy contrast, or Chapter 7's held-out comparison. Any further study receives its own recorded scope and conditions; keep all old results and unfavorable preflight outcomes.

Outputs: `experiments/mac-preflight/2026-11-09-7b8b/` for immutable fixtures, per-request bodies/responses, telemetry, result and manifest; a dated project note and matching dissertation/plan updates. No new participant data, paid API, external upload, message send or publication is included.
