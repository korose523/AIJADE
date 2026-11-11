# P2-A model-tokenizer and chat-context capacity preflight

11 November 2026 (Asia/Seoul). Continue the author's project/manuscript request and CAS category-2-or-above target. This preparation starts from archive 2ea5e010a5acab69b4f51b85673d25315e946bf9, its 422 proposed tasks and 115,185 retained cases. No task/domain approval, model-study split, primary seed, N/q/T or device qualification is inferred from this step.

## Fixed inputs and source matching

Use the already local Qwen2.5-Coder 7B Instruct and Llama 3.1 8B Q4_K_M model manifests. Record full manifest, model-blob, effective template, default-system and parameter identities, actual library/tool versions and source references. Reuse existing installations. Current inventory finds Ollama 0.40.6 and its installed libllama 0.7.0-dev. The official Ollama tag resolves to 2476d5ead197abe04629651028f83d48dc75d2b2 and pins llama.cpp b11669; check this source/runtime relationship and vocabulary controls before measurement. Model weights and local service configuration remain unchanged. Any missing or mismatched evidence remains explicit.

The actual research backend sends one user message to /api/chat. Obtain the effective local model template and default system, and reproduce that formatting through the pinned template implementation or a source-checked renderer. If an owned loopback service is needed, use it only for metadata and empty-loaded-model inspection, retain its handle and stop only that owned process. No /api/chat or /api/generate inference request is made. No task prompt is sent to an external service.

## Complete prompt corpus and tokenization

Export the actual generation, verifier A/B with reference candidate and verifier A/B with the fixed empty candidate from the C# builders, one task at a time without sandbox execution. Preserve all 2,110 raw prompt identities and require the same UTF-8 lengths and hashes as the preceding complete replay. Do not hand-transcribe the prompts.

For each model and prompt, retain the raw prompt and chat-formatted identities and actual token IDs/counts. Use the installed source-matched vocabulary-only tokenizer, without creating a model-inference context or reading tensors for execution. Distinguish the scheduler's tokenization flags from the completion path's special-token flags; report any BOS/EOS difference. Cross-check against an independent BPE implementation constructed from the exact local GGUF vocabulary, merges and documented pre-tokenizer. Do not substitute another model's tokenizer. Freeze implementations, sources and fixtures before the complete pass; archive any failed implementation/ABI/format attempt separately.

Fixed tokenizer controls include empty/ASCII/code text, leading/trailing whitespace, CRLF, decimal and long integer text, Chinese/Korean, combining characters, emoji and literal model special-token strings. Check token identities and reversible text where defined, including automatic special tokens separately. A mismatch blocks claims of verified tokenization; partial results and differences remain recorded.

One vocabulary process at a time. Per-model complete tokenization limit: 1,200 CPU seconds, 1,800 wall seconds, 2 GiB sampled RSS and 512 MiB process output. Individual prompt transport is limited to 1 MiB of UTF-8 input. Retain missing/error rows against the full planned population. Record process, binary, input, source and output hashes. Full model-file hashes are checked once before measurement with before/after file identity checks; no weights are uploaded.

## Capacity ledger and next-stage design

For every task/model/prompt, report exact token counts and input-only fit at context sizes 4,096, 8,192, 16,384 and 32,768. Separately report conservative input-plus-output-reserve fit for reserves 256, 1,024, 2,048 and 4,096. These are prospective budget scenarios, not device-memory allocation, measured inference performance or a selected primary setting. Do not silently truncate prompts, discard tasks, or alter the oracle's full test suite.

If the existing full-input prompt cannot fit, produce an explicit next-stage proposal for deterministic prompt-input exposure and reply budgets, with the untouched full oracle and original full-input measurements retained. Any implemented selection rule receives a separately fixed amendment before new measurement/model calls. Neither reference code nor empty-candidate probes represent the eventual distribution of model-generated code.

## Evidence and papers

Independently recompute case/task/prompt joins, token/control agreement and all fit counts; reject corrupted token identities, missing rows and changed template identities. Update the English/Chinese P2 material, full dissertation and review/evidence records, keeping the earlier byte-only stage identifiable. Keep preparation detail in the journal supplement and the full method in the dissertation. Rebuild/check final PDFs, publish source/evidence and verify exact GitHub CI. No model completion, training, answer-quality or verifier-reliability observations are produced by this preflight.
