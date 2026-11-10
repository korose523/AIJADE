# P3-E current shared-runtime measurement, 10 November 2026

## Decision and timing

The author explicitly requested, in the current chat, a full-corpus measurement of the updated product, manuscript/evidence updates and GitHub publication. This plan is committed and pushed separately before new instrumentation or corpus execution. It is a version-fixed follow-up to the 5 November P3-E plan, not external preregistration or evidence of supervisor approval. The author's instruction to proceed authorizes this Mac run; no supervisor send/receipt is invented and no message is sent. The earlier scope-file requirement to send a plan PDF before coding is not represented as satisfied. This exception is disclosed here before execution.

Measured product base: `d9dcf6bdc928f822e7a2fc3bf4e2cb00a36ebade`. The product runtime and frozen memory files will remain byte-identical. An instrumentation-only commit will follow this plan; both commits, product source hashes, actual test/client/server binary hashes and run commands will be recorded. No P2 generation, training, other research kernel change or real-user data is authorized by this study.

## Question, data and entry

How much gold evidence reaches the actual model request through the updated shared runtime, and how much is lost between the candidate pool, server responses, the five planned items and the complete items observed in the request?

Use all 10 conversations and all 1,986 questions in the existing LoCoMo file, SHA-256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`. The 1,540 answerable questions are primary; all questions and the located-evidence denominator are secondary. Questions listing no evidence remain explicitly counted but have no recall denominator; unlocated evidence is retained in the primary denominator. The conversation, not the question or memory item, is the resampling unit.

The entry is `CompanionRuntime.Create` with the actual `MemoryRecallProvider` enabled and other optional modules absent. Defaults are 4,000 UTF-16 code units per module, 12,000 supplemental, 24,000 history and 8,000 tool-result units, plus the shared visible-reply instruction. Record actual configured values. Use `ChatOrchestrator.SendAsync` to the completion request, the real server API and isolated PostgreSQL store, and a local completion-response stand-in. No chat model produces or judges answers.

Each question is a user-initiated single turn with empty supplied history, against the ingested conversation; questions and stand-in replies do not enter the memory evidence store. Perceptions are written synchronously through the API, with the established corpus timestamp/text encoding and ownership checks. This is a full-corpus measurement of this explicit product configuration. It does not include the full Web/QQ host, accumulated conversation history, companion life context, question recording, reminders or proactive messages, and must never be called a measurement of all product features. First and later corpus questions all use the same single-turn entry. Browser/QQ rendering and real recipient delivery are outside scope.

## Conditions and execution

1. Text retrieval, with no embedding route.
2. Embedding retrieval through existing local Ollama `nomic-embed-text`, no task prefix, manifest SHA-256 `0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f`, model layer SHA-256 `970aa74c0a90ef7482477cf803618e776e173c007bf957f635f1015bfcfef0e6`.

Run text then embedding, sequentially on this Mac, a fresh isolated store per conversation and condition. Do not reuse historical vectors/results or pool conditions into a treatment-effect estimate. No model download is needed. A one-hour harness request deadline retains the historical instrumentation allowance for first-search store embedding; the product's ordinary timeout is not changed. Cold initialization and failures are retained. Timings include instrumentation and machine load and are descriptive, not a product-latency benchmark or a causal mode comparison.

The existing observer is already qualified on seven synthetic API/database fixtures. Before the full run, qualify added transport recording/checkpointing with synthetic or bounded smoke inputs, recorded separately from corpus results. Test-only recording may capture the actual gateway embedding vectors to recompute the server response without making a second embedding request for the same query. That is an observation of actual upstream results, not a substitute embedding implementation, and no product response or request text is changed. Missing/malformed embeddings and text fallback must be exposed rather than counted as successful semantic retrieval.

No outcome-based stopping or selection of a favorable run. Preserve attempts, including partial/failed ones. A host/service/instrument failure permits a documented restart in a fresh output directory, retaining the earlier attempt. One complete pass per condition is the target, not a repeatability claim. Do not fill missing rows from a different attempt without labeling that analysis separately. If resources become unusable or a request times out, retain the completed rows and diagnose before resuming; success is not inferred from an exit code alone.

## Observation and retained evidence

Keep distinct stages: stored, pool, above threshold, server-response union, echo-filtered, planned five newest, and observed complete memory items. Ranking is not an additional loss stage. Capture the actual system request, server query/response IDs and contents, full planned IDs, complete observed IDs, truncation/ambiguity state, completion status and calls. Partial text never counts as a whole memory item. Capture is not evidence that a model used the text or that the text is true. ID attribution is conditional on the provider's deterministic order and unique content.

Use create-new outputs and append per-question observations durably, so a failed long run retains earlier observations. Retain per-conversation source/store snapshots and embedding observations needed for response recomputation; lossless compression is allowed. Preserve SHA-256 manifests, model/service identity, run start/end and actual binaries. The format remains separate from v1 archives and the historical v1 aggregator. Any schema extension is explicit. No old numerical JSON is overwritten.

Record empty responses, fewer than five kept items, term-search use, provider not consulted, missing captures, ambiguous sources, partial clipping, failed turns, failed writes, fallback and response-recomputation mismatches separately. An unexplained capture or recomputation mismatch is an instrument failure, not a research zero. Expected attribution ambiguity is unknown, not zero; it does not disappear from the population accounting.

## Analysis fixed before execution

Primary quantity: candidate-pool recall minus actual complete-item prompt recall, per question's listed evidence, averaged within each conversation and then across conversations. Also report the consecutive losses and the planned-to-observed difference. Use paired conversation bootstrap, 10,000 percentile resamples, seed `20261110`; report mean, 95% interval, contributing questions and conversations. No directional test or cross-mode significance claim is planned.

If all eligible prompts are identifiable, the primary estimand is a point estimate with its interval. If some are unknown, retain the full target population and provide conservative bounds by assigning each unknown prompt recall 0 or 1; complete-case estimates are labeled secondary and give their denominators. No listwise deletion disguised as the primary analysis. Report answerable, all-question and located-evidence views separately.

The server's first five items and the planned newest five are upstream, pre-budget descriptive arms; they are not an actually delivered alternative under an equal prompt budget. Describe the actual budget loss separately. Historical versus current point differences are version comparisons across recorded runs, not randomized causal effects; preserve the historical figures and their original source identities. A zero difference is reported as measured, not as proof of equivalence.

Completeness checks require every `(conversation, question)` exactly once in each complete condition, all 10 conversations, corpus/model identity, binary/source identity, full write accounting, genuine completion/capture accounting, and reproducible aggregate calculations. Negative results and unresolved instrument failures are retained. No answer accuracy, full policy comparison, human utility or Chapter 7 acceptance follows from this measurement.

## Manuscript and software workflow

Update P3 English/Chinese §5.12 and availability/limitations, the corresponding dissertation chapter and Appendix A, using a new current-version result namespace. Keep historical tables and source data traceable. Put raw provenance and long diagnostics in the evidence package; place the new result, its uncertainty and material scope limits in the main text. Public code/results are pushed before binding final paper PDFs to the new public commit. Rendering, CI, scientific inference and final submission approval are separate checks.

Experimental-design/resource checks use Scientific Agent Skills; the workflow source is Kassis, T., Agarwal, V., He, Y., Patel, D., and Brueckner, A. M. (2026), *Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents*, arXiv:2609.00065, https://doi.org/10.48550/arXiv.2609.00065 (metadata verified 10 November 2026, current record v2). This acknowledges procedural assistance and does not validate the experiment's findings.
