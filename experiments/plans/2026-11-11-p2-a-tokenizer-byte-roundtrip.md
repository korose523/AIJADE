# P2-A tokenizer byte-roundtrip amendment

11 November 2026 (Asia/Seoul). Amend the separately published capacity plan aaf5a3c. This is a recording/API correction after an observed complete-pass failure, not a prospective claim about that failed pass. Preserve complete-01, complete-02 and all control attempts separately; no prefix or model rows from those attempts enter the accepted rerun.

## Observation and cause

At frozen source 5aaf7e7 the 26 original controls passed, and the Qwen complete pass agreed. The Llama complete pass produced exact token-ID agreement but byte-roundtrip mismatches: for example, a generation instruction containing ` ```js ... ``` ` was returned by `llama_detokenize` without the blank before the ellipsis. The independent byte-level decoder retained the original text. The pinned llama.cpp b11669 `src/llama-vocab.cpp` sets `clean_spaces=true` for this BPE path and its convenience whole-sequence detokenizer removes some spaces before punctuation and contractions. Therefore the original assumption that that API is byte-reversible for code was false. This does not by itself indicate a tokenization disagreement or a model-completion error.

## Fixed correction before implementation and new execution

Keep tokenization flags, vocabularies, merges, actual templates, all 2,110 task prompts and their prior hashes, full oracle, contexts, reply reserves and resource limits unchanged. Use the public `llama_token_to_piece` API with `lstrip=0` and `special=true`, concatenate the exact returned bytes, and compare that uncleaned byte stream with the independent byte-level decoder and the expected raw/chat text, including automatic special tokens separately. Do not change model vocabulary flags, model files or inference behavior. Change the framing magic to P2TOK02 to identify this recording API. Preserve the original whole-sequence-detokenize records as failed diagnostics.

Add two fixed regression controls to the original thirteen: punctuation/contraction whitespace (`a . b , c ! d ? I ' m you ' re`) and fenced-code/indented whitespace (` ```js ... ``` ` plus multiline leading/trailing blanks). These are post-failure diagnostic additions, not retrospectively preregistered controls. Re-render the 15 controls for both models with the same captured templates; the complete corpora must be byte-identical to the preceding export. Freeze this amendment separately before code changes, then freeze corrected code and binary hashes before running all 30 controls and both complete model passes from the beginning. No inference requests, training or task eligibility selection are introduced.

## Acceptance and reporting

Accept only both complete passes with all 4,220 rows, four views per row, exact token IDs and exact uncleaned byte roundtrips. Independently parse both lossless streams and recompute all joins, counts, hashes and capacity scenarios; reject altered token IDs/counts/hashes, missing rows and template changes. Archive complete failed attempts, including the clean-space mismatches, and label the corrected byte-piece decoder explicitly. Source revision matching remains limited because the installed Ollama reports vcs.modified=true. Vocabulary-only and old saved cold-request checks do not qualify device memory or new long-prompt prefill. No truncation or primary design is selected by this correction.
