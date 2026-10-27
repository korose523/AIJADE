# P3 Tables 1–9 on the answerable questions (plan, 27 October 2026)

**Status.** Written and committed to this repository **before** the analysis code below is written. It is not registered
on an external platform. It was requested by the supervisor's review of 27 October 2026 (§5.6 and §7, second answer). The
analysis uses only data that already exist (the hash-pinned LoCoMo corpus and the archived memory runs); there are no model
calls, no new generations and no paid resources. Following the supervisor's schedule, the computation is done after
2 December 2026 and before Chapter 6 of the dissertation and P3 are revised. Because the full-sample results are known,
this is a re-analysis of known data: what the plan fixes in advance is the specification and the reading, not the data.

**Why.** The abstract, Highlights, Table 10 and the conclusion of P3 use the 1,540 answerable questions (LoCoMo category
≠ 5), but Tables 1–9 use all 1,986 questions, so the same quantity can appear with two values (for example 7.75 of the
top 8 newer than the evidence in the abstract, 7.73 in Table 1; recall@8 0.086 → 0.349 in the abstract, 0.0906 → 0.3580 in
Table 2).

**Code version.** The analysis code is written after this commit. The output records the code commit
(`AIJADE_GIT_COMMIT` or `git rev-parse HEAD`) and the commit of this plan.

**Deviations.** Any change to what is written here, made after this commit, is listed in the output file and in the papers
as a deviation from the plan, with its reason and date.

## Inputs (fixed)

| Input | SHA-256 |
|---|---|
| LoCoMo `locomo10.json` | `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4` |

The memory stores are built exactly as in the archived runs. The store does not depend on which questions are scored, and
retrieval does not change the store, so only the set of scored questions changes.

## Tables

| P3 table | Quantity | Treatment |
|---|---|---|
| 1 | Recency of the default additive top 8 (no gating) | Re-computed on the 1,540 answerable questions |
| 2 | Weight ablation (diagnostic track, micro, K = 8, fixed pool; last column over the whole store) | Re-computed |
| 3 | Mean score components (no gating) | Re-computed |
| 4 | Delivery-track `recall@8` by score mode, with the conflict penalty switched off in the last column | Re-computed |
| 5 | Effect of salience gating (ON − OFF) on delivery-track `recall@K` | Re-computed, same K values |
| 6 | Salience source × gating at K = 8 | Re-computed |
| 7 | Decomposition of the gating effect at K = 8 | Re-computed |
| 8 | Leakage audit of the salience model (turn level) | Unchanged: it does not depend on the question set |
| 9 | Headline measurements on both corpora | LoCoMo column re-computed; the LongMemEval_s column is unchanged (its abstention questions have no marked evidence and are already left out) |

Each re-computed table keeps the definitions, K values, score modes, floors and interval methods of the archived table.
Questions whose evidence turn cannot be resolved in the store are handled as in the archived tables and their number is
reported for each question set.

**Reproduction check (before anything is read).** The same code also computes every table on all 1,986 questions. These
values must reproduce the archived files (`memory/weight-ablation.json`, `component-scales.json`, `delivery-check.json`,
`gating-interference.json`, `salience-sources.json`, `k-dependence.json`, `uncertainty.json`, `pool-check.json`) to the
printed precision. Any mismatch is reported and resolved before the answerable-question values are used.

## Output

`memory/answerable-tables.json`: for each table, the values on the 1,540 answerable questions and on all 1,986, the counts
of questions without resolvable evidence, the reproduction check, the plan commit, the code commit and the input hash.

## Reading (fixed)

- The 1,540-question tables become the tables of P3 and of Chapter 6; the 1,986-question tables move to a sensitivity
  appendix. Table 8 stays where it is.
- The text of P3 and Chapter 6 is rendered from the new values. Where a direction or a stated comparison differs between
  the two question sets, both are reported and the text follows the answerable-question value.
- No new hypothesis is tested; the re-computation is not called confirmatory.
