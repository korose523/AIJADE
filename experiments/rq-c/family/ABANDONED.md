# Abandoned first attempt at the second-family control (llava-phi3)

`rq-c-s42-ollama-t30-r5/` holds the first 5,505 of 7,200 steps of the pre-registered design run with `llava-phi3:latest`
(Phi-3-mini based vision-language model) on the Mac, started 2026-10-15 19:22, resumed once from step 1608 (record in
`interrupted/`), and stopped by hand on 2026-10-18 at 18:55. It has no `summary.json`.

Why it was abandoned: the model's verifier replies do not begin with PASS or FAIL as the prompt asks (they list the cases
and end with "Overall verdict: …"), so under the pre-registered rule every verdict is FAIL; no skill is admitted and every
step regenerates, which made the run measure format compliance rather than self-assessment (and very slow on this CPU-only
host). The author chose on 2026-10-16 to keep it running under the pre-registered rule, and on 2026-10-18 to replace it with
a run on the Windows GPU host under a model-selection rule fixed before testing (see the papers workspace
`稿件源/parts/PENDING.md`); that run is `../family-gpu/` (llama3.1:8b). The record is kept as data for the paper's account
of the attempt; nothing in it was deleted.
