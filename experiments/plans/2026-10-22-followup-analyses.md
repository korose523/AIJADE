# Follow-up analyses on existing data (plan, 22 October 2026)

**Status.** Written and committed to this repository **before** any of the analyses below was implemented or run. It is
not registered on an external platform; the papers cite it as "planned before execution and committed at <commit>",
never as pre-registered. The analyses were requested by the first supervisor review of the papers (22 October 2026):
P3 §3.2(1)–(3) and P2 §2.2. They use only data that already exist (the hash-pinned LoCoMo corpus and the recorded RQ-C
runs); there are no model calls, no new generations and no paid resources. Because the full-sample results of P2 and P3
were already known when this plan was written, every analysis here is a re-analysis of known data; what the plan fixes in
advance is the specification and the reading of each result, not the data.

**Code version.** The analysis code is written after this commit. Each output file records the code commit it was
produced from (`codeCommit`, from `AIJADE_GIT_COMMIT` or `git rev-parse HEAD`) and the commit of this plan.

**Deviations.** Any change to what is written here, made after this commit, is listed in the output file and in the papers
as a deviation from the plan, with its reason and date. Analyses not listed here are labelled exploratory.

## Inputs (fixed)

| Input | SHA-256 |
|---|---|
| LoCoMo `locomo10.json` | `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4` |
| `rq-c/redo/rq-c-s42-ollama-t30-r5/trials.jsonl` (main, qwen2.5-coder 7B) | `d7532c6f81dc3435f752e5a60f360e97a6d12fd29ade5eb2fcbd55a9bd8b6dae` |
| same, `candidates.jsonl` | `bbd6e0b8f95976fff16bc7c35302d10d97854c94b564c504e2f498e2e02371a0` |
| `rq-c/family-gpu/rq-c-s42-ollama-t30-r5/trials.jsonl` (second family, llama3.1:8b) | `56e40a5e54d6a3bbe2884d25bf5e6049d2dd4ecb5c338a177764d709766b4121` |
| same, `candidates.jsonl` | `9f53d82b6e38ff5286fc62c062cc54579d7a6e8fa9a1b1232f84bea486ce4d61` |
| `rq-c/template-gpu/A/rq-c-s42-ollama-t30-r5/trials.jsonl` (prompt template A) | `73dfd090ff3410f1a24e62ff75ab69b0bab90a01fbedfe502ad285f7b6b18436` |
| same, `candidates.jsonl` | `928a99838f7b57696c2e7fe4731bc3b2890b16c2ed7ef9461d1ad3dae61d2ae3` |
| `rq-c/template-gpu/B/rq-c-s42-ollama-t30-r5/trials.jsonl` (prompt template B) | `fc76a3cc69ed351108052c68772902a03b936aa728c28542a0de3ad74c7b07c0` |
| same, `candidates.jsonl` | `fd4b5408eb2592a9322728e23b51ad669f82bbdcdc8d7b5365636a3ef9439be2` |
| `rq-c/rq-c-s42-mock-t30-r5/trials.jsonl` (simulated positive control) | `dfa9ac6645de0f2b938a453c8131545f367d1fc8c08964fe736646cc0c7aeb7f` |
| same, `candidates.jsonl` | `b63d55fd3b089831d2d6db1f31e0daa8defebe2f00571d99787e51208b33a1e9` |

---

## P3-A Answerable questions only; recall counted per evidence turn

**Question.** Do the headline contrasts of P3 hold when the 446 adversarial questions (LoCoMo category 5, unanswerable
from the conversation by the corpus's own definition) are left out?

**Subset.** The 1,540 questions with category ≠ 5. The memory stores are built exactly as in the published runs (the
store does not depend on which questions are scored, and retrieval does not change the store), so only the set of scored
questions changes. Each quantity is also computed on all 1,986 questions by the same code; these all-question values
must reproduce the archived files (`memory/uncertainty.json`, `pool-check.json`, `delivery-check.json`,
`gating-penalty-off.json`) to the printed precision, and any mismatch is reported before anything is interpreted.

**Quantities (K = 8; hit = an evidence turn or its fact copy in the top K with a store score above the retrieval floor,
as in the papers).**

1. Recency of the default additive ranking inside the 150-candidate pool: mean number of top-8 items newer than the
   newest evidence turn, against the unbiased expectation.
2. Diagnostic track, 150-candidate pool, floor applied: recall@8 with similarity alone (`sim-only`) against the default
   weights (`current`), micro over questions.
3. The same contrast over the whole store, judged on rank alone.
4. Delivery track without gating, standardised score: recall@8 (macro over conversations) with the conflict penalty at
   its default (0.5) and switched off (1.0); the additive score is reported alongside.
5. Gating ON − OFF at K = 8 with the deployed (predicted) salience, under three scorers: additive (default penalty),
   standardised (default penalty), standardised (penalty off). Macro over conversations.

**Uncertainty.** As in P3: the conversation is the unit of dependence; conversation bootstrap (10,000 resamples, seed
`0x5EED2026`, percentile 95 %) and the exact sign-flip test over the 10 paired per-conversation differences
(2¹⁰ assignments; smallest attainable p = 2/1024). Micro contrasts resample whole conversations and keep the pooled
caliber; macro contrasts use the mean of per-conversation differences.

**Auxiliary measure: per-evidence recall@8.** For a question with at least one evidence turn present in the store, the
share of its distinct evidence turns that are hit (episode or fact copy, top 8, above the floor). Questions with no
evidence turn in the store are left out of this measure (they count as misses in hit-any recall). Reported for the
configurations of items 2, 4 and 5 (gating OFF and ON), on answerable and on all questions, and separately for
questions with at least two evidence turns in the store; same calibers and intervals as the corresponding hit-any
quantity.

**Reading fixed in advance.** If a contrast on the answerable questions changes sign relative to its all-question value,
or its interval includes zero where the all-question interval did not, the corresponding P3 claim is rewritten on the
answerable-question result. Results that agree are reported in the same detail. The answerable-question values become
the primary values in P3; the all-question values are kept for comparison with the earlier version.

## P3-B Direct estimate of the gating × scorer interaction

**Question.** How much does the gating effect differ between scorers?

**Target.** For conversation c and scorer m, g_m(c) = recall@8(gating ON) − recall@8(gating OFF), predicted salience.
Two contrasts per conversation:

- Δ₁(c) = g_additive(c) − g_standardised(c) (default penalty in both);
- Δ₂(c) = g_standardised, penalty off(c) − g_standardised(c).

**Analysis.** Mean of Δ over the 10 conversations; conversation bootstrap (10,000, seed `0x5EED2026`, percentile 95 %)
and exact sign-flip test. Computed on the answerable questions (primary) and on all questions. The two answerable-question
p-values are also Holm-adjusted as a family of two.

**Reading fixed in advance.** Interval excludes zero: "the gating effect differs between the two scorers (interaction
detected)", with its direction and size. Interval includes zero: "no interaction detected"; never "no interaction".

## P2-C Does environment feedback change the verifier's error rates? Stability over rounds

**Runs.** Main (qwen2.5-coder 7B), second family (llama3.1:8b), prompt templates A and B (7B, GPU host), each in its two
self-verification-on cells (`sv1-ef0`, `sv1-ef1`). The simulated positive control, whose injected error rates (0.30
false pass, 0.10 false fail) do not depend on feedback, is analysed with the same code as a check: its feedback
difference should be close to zero and its rates close to the injected ones.

**Unit and truth.** The skill, as in P2 Table 2: a skill with a self-verdict and an execution result; truth = the outcome
of its last execution; positive = self-pass. hallucinationRate = FP/(FP+TN) (false pass among unusable skills);
missRate = FN/(FN+TP) (false fail among usable skills).

**Design note.** The verifier prompt holds only the task and the candidate code (`BuildVerifyPrompt`,
`BuildVerifyPromptB`), never the environment feedback. Feedback therefore acts on the error rates only through which
candidates are produced. The target is the error rate on the candidates produced under each feedback condition.

**Question 1: feedback.**
- Each rate in `sv1-ef0` and `sv1-ef1`, and the difference ef1 − ef0. Interval: task-cluster bootstrap (10,000 resamples
  of the tasks, the same draw used for both cells, seed `0x2545F491`, percentile 95 %).
- Logistic regression of "verdict wrong" on ef (intercept + ef), fitted separately among unusable skills (wrong =
  self-pass) and usable skills (wrong = self-fail), maximum likelihood, cluster-robust (CR1) standard errors by task.
  If a group has no wrong verdicts, or only wrong verdicts, in one condition, the fit is reported as not estimable.
- Secondary: the same two rates on distinct candidates (task, code) within each condition, first judged verdict, as in
  P2 Table 2b, with the task-cluster bootstrap.
- Decoding non-determinism baseline: the (task, code) candidates judged in both conditions, and how many received
  different verdicts.

**Question 2: rounds.** A skill's round is the round of its first step (0–4).
- Each rate per round, pooled over the two self-verification-on cells, with the task-cluster bootstrap.
- Trend: logistic regression of "verdict wrong" on round (continuous) and ef, separately among unusable and usable
  skills, CR1 standard errors by task.

**Reading fixed in advance.** Estimates and intervals are reported for every run. A difference or trend is called
"detected" only when its 95 % interval excludes zero; otherwise "not detected", never "no effect". When fewer than five
tasks contribute unusable skills to a cell, the hallucinationRate comparison for that run is reported as descriptive
only. With wide intervals the papers make no claim that the error rates are "stable" or "unstable" over rounds.

## Outputs

- `experiments/memory/answerable-reanalysis.json` (P3-A, P3-B), driver command `aijade-experiments answerable-check`.
- `experiments/rq-c/verifier-feedback.json` (P2-C), driver command `aijade-experiments verifier-feedback`.
