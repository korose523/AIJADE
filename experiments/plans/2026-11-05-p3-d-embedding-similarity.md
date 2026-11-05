# P3-D: Is an embedding similarity suppressed by strength and recency the same way?

**Status.** Committed to this repository on its own on 5 November 2026, before its code. It is not registered on an external platform. By the first author's decision of 5 November 2026 this plan runs on the Mac before 2 December 2026 and without waiting for the supervisor's review: the field values marked below are the first author's proposals, not values the supervisor has agreed, and the plan was not sent to the supervisor before its code was written. The study is listed as optional in the supervisor's review of 27 October 2026.

*Last revised: 31 October 2026 (this header line added on 3 November 2026; checked again on 4 November 2026). Code statements checked against commit `97aab7c` of the code repository (the desk check was made at `767e98e`; the files it read are unchanged since).*
*Revisions: 31 October 2026 (desk check at `767e98e`, nothing run: what changes with the similarity term and what does not, what the embeddings are computed on, and a reading in the two observed quantities of P3-C).*

## Study information

**Research question.** The kernel's relevance term is TF-IDF cosine. If only that term is replaced by an embedding cosine, do strength and recency still dominate the ranking?

**Hypotheses.** None directional.

## Design plan

**Design.** Only the similarity component is replaced, by the cosine between embeddings from one local embedding model, nomic-embed-text v1.5 through Ollama (manifest SHA-256 `0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f`; first author's proposal); scoring weights, score modes, corpus, store construction and every other component are unchanged. The diagnosis of §5.1–§5.3 and the fixed-pool weight ablation of §5.2 (including the whole-store re-run) are repeated, plus the delivery check with the conflict penalty on and off in the additive and standardized modes (the paper's Table 4).

**What changes with the similarity term, and what does not (fixed now; code at `767e98e`).** In the kernel's retrieval (`src/Aijade.Memory/BioticMemory.cs`), the TF-IDF cosine of the lexical index is the first of four raw components; strength, recency and the context term (the overlap of query and item tags) are computed without it.
- *Unchanged:* the retrieval floor (0.02 on the store's own score), the conflict test (entity overlap with opposite negation, a lexical test on the text), the collapse of items with identical content, the retrieval noise, and the bag-of-words cosine inside the salience model, which is not the relevance term.
- *Changed by construction:* the diagnostic track's pool is the store's own top 150 under its default score, so it is drawn again under the embedding similarity. Its coverage of gold items is reported next to that of the TF-IDF pool, as in §4.2. The head of 150 that the conflict penalty scans in the standardized and RRF modes changes in the same way.
- Whether the floor removes any hit is reported under both similarities; under TF-IDF it removes none in the additive and standardized modes (§5.4).

The embedding similarity enters the kernel as an option whose default stays TF-IDF. The kernel is a research object, so before any run of this study, the regression of Chapter 6 (identity with the archived results) is re-run on the changed kernel and recorded in `docs/STATUS.md`.

**Embeddings (fixed now).** One embedding per distinct stored text and one per question. The kernel's lexical distiller stores each distilled fact as a verbatim copy of its turn (`LexicalDistiller`), so the stored texts are the turns' texts. If the model's documentation prescribes task prefixes for queries and documents, they are used as documented and recorded. The cosine is used as computed, negative values included. Embeddings are computed once and cached with the model digest.

## Sampling plan

**Existing data.** LoCoMo, the same release and hash as the paper; the 1,540 answerable questions are primary and all 1,986 are reported alongside.

**Sample size.** All 10 dialogues; the conversation is the unit of resampling.

## Variables

**Measured.**
- Top-8 items newer than the evidence, and its unbiased expectation.
- Mean score components of gold items, the additive top 8 and the pool, and the spread of each component within the pool (the quantity §5.3 uses to compare the components).
- The pool's coverage of gold items.
- `recall@8` of the weight arms on the fixed pool and on the whole store.
- Delivered `recall@8` with the penalty on and off.

## Analysis plan

**Statistical models.** As in the paper: conversation bootstrap and exact sign-flip test for the paired contrasts.

**Reading (fixed now, as in P3-C).** The study yields two observed quantities, each reported under its own name with its interval:
- (a) the change in fixed-pool `recall@8` (micro) from ranking by similarity alone, relative to the kernel's default ranking;
- (b) the number of top-8 items newer than the evidence, relative to its unbiased expectation.

A change in (a) by more than a factor of 2, or a value of (b) above 1.5 times the expectation, is marked as a descriptive diagnostic; with a baseline of zero, the ratio is reported as not available. If neither is marked under embedding similarity, the paper limits its claims about the dominance of strength and recency to TF-IDF similarity. If either is marked, the paper reports which, with its size, for this embedding model only. Both quantities describe the ranking. The score formula, which adds the components with fixed weights on one scale, is the same under either similarity; what the study measures is how much this matters when the distribution of the similarity changes.

## Other

**Plan and record.** This plan is committed on its own before its code is written. Its results are written to `experiments/memory/embedding-check.json`.

**Resources.** Embedding model download (permission required); local machine.

**Code version and deviations.** Runs set `AIJADE_GIT_COMMIT`; deviations are listed with date and reason.
