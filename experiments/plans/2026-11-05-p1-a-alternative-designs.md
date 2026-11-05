# P1-A: What do alternative designs detect, and miss, on fixed fault sets?

**Status.** Committed to this repository on its own on 5 November 2026, before its code. It is not registered on an external platform. By the first author's decision of 5 November 2026 it runs on the Mac before the supervisor's review: the values that were open fields are the first author's proposals, not values the supervisor has agreed, and the plan was not sent to the supervisor before its code was written.

*Last revised: 3 November 2026; checked again on 4 November 2026. Code statements checked against commit `97aab7c` of the code repository (the desk check of set 1 was made at `767e98e`; the files it read are unchanged since).*
*Revisions: 27 October 2026 (supervisor's review: the research question no longer assumes that the paper's design detects every fault, an input- and data-layer fault set and faults that the alternatives are built to catch are added, and the original 42 faults become a separate diagnostic checklist); 31 October 2026 (desk check of where each class of set 1 enters the pipeline); 3 November 2026 (supervisor's review: the size of set 2 is a decision field, the reading when the paper's design detects more is fixed, results name the form in which each fault was given, and the rules of each configuration are fixed in a table).*

## Study information

**Research question.** On fixed sets of faults, how many does each of four configurations detect, where, at what cost, and how much faulty data has already been written and read downstream when it does? How often does each refuse valid input? The paper's design is not assumed to detect every fault.

**Hypotheses.** None. The authors expect liberal acceptance to miss envelope-shape faults, after-the-fact lineage to detect some faults only after contaminated rows exist, and consumer-driven contract tests to catch semantic changes that the paper's design misses. These expectations are not tested; the study reports what each configuration detects whatever the outcome.

## Design plan

**Study type.** Experiment on software configurations (no human participants).

**Design.** Four configurations × three fault sets; every fault is run against every configuration to which it can be given.

1. *Paper design*: strict boundary, render identity chain, admission check and three promotion gates (the code at the registered commit).
2. *Liberal acceptance*: the boundary tolerates unknown keys and fills missing fields with defaults; everything else unchanged. Implemented as an experiment-only switch extending the existing timing-only `TolerateUnknownKeys` option in `src/Aijade.Server/V9/Boundary.cs`.
3. *Consumer-driven contract tests*: neither the boundary's nor the kernel's schema is used for validation; each consuming component carries expectation tests for the topics it reads, written from the consumer's code, not from the paper's fixtures. These tests run before deployment.
4. *After-the-fact lineage*: all writes are accepted; an audit job run after each fault lists dangling references and unpaired identities from the stored data. Its observation window is fixed before the runs.

All configurations receive the same inputs and the records available to them.

**What each alternative keeps (fixed now).** An alternative replaces only the mechanism named in its description, the one the paper compares it with (§6); every other component is that of configuration 1, and the promotion gates run in all four. Configuration 3 therefore validates no input against a schema at run time, so an input that one of its consumers cannot read fails at that consumer, but it keeps the identity-chain rules and the admission check; configuration 4 has no refusal at writing (no schema validation, identity-chain rule or admission check). The pre-deployment checks are the drift matrix and the promotion-gate matrix for configuration 1; the same matrices without the assertions that liberal semantics contradicts, each listed, for configuration 2; the consumer expectation tests and the promotion-gate matrix for configuration 3; and the promotion-gate matrix for configuration 4.

**Rules of each configuration at each stage (fixed now).** Each alternative is a hybrid: it changes one mechanism of configuration 1 and keeps the rest, so its results speak about this configuration, not about liberal acceptance, consumer-driven contracts or lineage audits in general.

| Configuration | Before deployment | Admission (boundary and admission check) | Write | Promotion | After the fact |
|---|---|---|---|---|---|
| 1 Paper design | Drift matrix and promotion-gate matrix | Strict schema; identity-chain rules; admission check | Event and projection in one transaction | Three gates | None |
| 2 Liberal acceptance | The two matrices without the assertions that liberal semantics contradicts (each listed) | Unknown keys tolerated, missing fields filled with defaults; identity-chain rules and admission check as in 1 | As in 1 | Three gates | None |
| 3 Consumer-driven contract tests | Consumer expectation tests and promotion-gate matrix | No schema validation at run time (a consumer that cannot read an input fails there); identity-chain rules and admission check as in 1 | As in 1 | Three gates | None |
| 4 After-the-fact lineage | Promotion-gate matrix | None: no schema validation, identity-chain rule or admission check | As in 1 (nothing refused) | Three gates | Audit job after each fault, in an observation window fixed before the runs |

**Giving a fault to a configuration (fixed now).** Each run starts from a freshly migrated database. A fault defined on inputs or stored data (set 1, the semantically wrong records of set 2, and N1–N9) is posted through the configuration's HTTP API after the valid inputs it needs (for example a paired trace); a fault at the promotion stage is placed on the promotion queue as a job document, which the worker passes to the promotion service. A fault defined on code (the changed units or meanings of set 2, and the 33 mutants of set 3) is applied to a copy of the configuration's source tree, as the paper's mutation tool does; the configuration's pre-deployment checks are run, and then the inputs of the end-to-end chain (§5.2) are posted as its workload, followed in configuration 4 by the audit job. A fault is detected at the first check that fails on it or refuses it. A code fault whose changed code is absent from a configuration is not applicable there.

**Blinding.** None (automated).

## Sampling plan

**Existing data.** None; all outcomes are generated by new runs.

**Fault sets (fixed before any run, not adjusted to results).**
1. *Input- and data-layer faults.* Faults defined on inputs and stored data, not on the code, in eight classes: missing source, wrong memory reference, stale skill, self-assessment false pass, success reported for a failed execution, missing or out-of-order receipt, parameter or asset mismatch, and duplicate. Valid inputs are mixed in so that false refusals can be counted. Three cases per class (24) and 24 valid inputs. Where each class enters the pipeline was checked in the code (desk check, 31 October 2026, at `767e98e`; nothing run), and every class can be given to all four configurations:
   - a missing source, as a learning proposal without `render_ref` or citing a render absent from the projection (the boundary's required field, or the admission check's render-not-found branch);
   - a wrong memory reference, as an envelope's `evidence_refs` or the `candidate_memory_write_ids` of `aijade.evidence.weave_candidate_ready` naming records that do not exist (no check of configuration 1 reads them; the citation-domain validator of §4.2 is called by no endpoint or worker);
   - a stale skill: the pipeline holds no skill records, so the class is given in its nearest form, a proposal citing a real, paired render that a later receipt has superseded (the admission check compares a proposal with the receipt of the trace it cites, not with the latest one);
   - a self-assessment false pass, as a promotion job whose evaluation pack declares its core tests passed while counting failures (the evidence gate reads only the declared verdicts);
   - a success reported for a failed execution, as a render receipt for an intent the renderer did not apply (a receipt carries no execution status);
   - a missing or out-of-order receipt, as a request left without a receipt, a receipt before its request (accepted by design and recorded as a pairing gap in the audit log), or a proposal citing a trace without a request (the admission check's intent branch);
   - a parameter or asset mismatch, as a proposal whose fingerprint or asset version differs from its receipt's (the admission check);
   - a duplicate, as a replay under the same idempotency key (deduplicated) or the same event under a new key (stored again, as only the idempotency key is unique in the event table).
2. *Faults the alternatives are built to catch.* Changes that a consumer's expectation test catches while the schema stays valid (for example a field whose name and format are unchanged but whose unit or meaning has changed; the schema fixes no unit for, among others, the character offsets of `spans` and the millisecond times of `time_spans`), and records whose identifiers are correct but whose content is semantically wrong. Five cases of each of the two kinds.
3. *Diagnostic checklist from the paper's design.* The 42 known faults: the 18 executable mutants of the drift matrix (`tools/Aijade.Mutation/mutations.json`), the 15 reachable mutants of the promotion-gate matrix (`tools/Aijade.Mutation/gate-mutants.json`) and the 9 boundary-negative inputs N1–N9 of the end-to-end cases (unauthenticated request, missing `tick`, empty input fingerprint, unknown envelope field, unknown topic, missing `intent_ref`, self-reference, append-only conflict, malformed JSON). They were made from the paper's design, so they are reported separately and not pooled with sets 1 and 2.

Sets 1 and 2 are made by the researcher who built the design. Their independence from the design, and how well they stand for faults in general, are stated with the results.

**Sample size and stopping rule.** Each fault × configuration cell is run once (its outcome is deterministic on a freshly migrated database; its detection time is a single measurement). No stopping rule.

## Variables

**Manipulated.** Configuration (four levels); fault set (three sets, analyzed separately).

**Measured.**
- Per fault × configuration: detected (yes/no); detection point (before deployment, boundary, write time, a consumer, gate or after-the-fact audit) and time; rows written before detection, and of those, rows read by a downstream consumer (worker or projection).
- Per valid input × configuration: accepted, refused or unknown.
- Per configuration: setup and running time, and the cost of maintaining its checks, given as the lines of check code and fixtures it needs at the code commit and the time spent writing them, as recorded by the author.

## Analysis plan

**Statistical models.** None. The fault sets are finite and made by hand, not samples from a population of faults, so no significance test is run and no detection rate over all faults is estimated.

**Reporting.** For each fault set, a table of detections, refusals of valid input and contamination per configuration, and a per-fault list of what each configuration misses. Each fault is named by the form in which it was given (for example "a proposal citing a paired render whose receipt was superseded"), not by its class ("stale skill"); classes given only in their nearest form are marked so. The mutation scores of the paper (9/18 and 13/15) measure how much of the code mutants the test matrices detect; they are a different quantity from the shares of faulty inputs a configuration detects and are not compared with them.

**Inference criteria (fixed in advance).** If an alternative configuration detects every fault of sets 1 and 2 that configuration 1 detects, the paper limits its claim against that alternative to the measured differences in detection point, contamination, refusals of valid input and cost, and states which configuration each difference favors; faults that configuration 1 misses and an alternative detects are listed as limits of the design. If configuration 1 detects faults of sets 1 and 2 that an alternative misses, the paper states this as a difference on these sets, which the researcher who built the design made, between configuration 1 and that hybrid configuration, not as an advantage over that kind of alternative in general. These results are reported as found. Results on set 3 are reported as a diagnostic checklist and are not used for this criterion.

**Data exclusion.** A fault that cannot be given to a configuration (for example a boundary mutant when the boundary is removed) is reported as "not applicable" with the reason, not dropped.

**Missing data.** A run that crashes is re-run once on a fresh database; a second crash is reported as such.

## Other

**Code version.** Configuration switches, consumer tests, the audit job and fault sets 1 and 2 are committed together before any configuration is run on any fault; runs set `AIJADE_GIT_COMMIT`, and the results file records this plan's commit and the code commit. The code commit cannot be given here, because this plan is pushed before that code is written.

**Plan and record.** This plan is committed on its own before its code is written. Results go to `experiments/p1/alternative-designs.json`. The audit job of configuration 4 runs immediately after each fault, so its observation window is that one read.

**Resources.** Local PostgreSQL; recreating the local database container needs a container image download (permission required). No language model, no paid service.

**Deviations.** Any change after registration is listed with its date and reason in the results file and the paper.

## Addendum: the code faults and the consumer tests (committed before their code)

**Why this addendum.** The input and data faults ran first (`29a5271`). The plan's Code version rule, that consumer tests, the fault sets and the switches are committed together before any configuration runs on any fault, can therefore no longer be met for this part. By the first author's decision of 5 November 2026 this part is added anyway and listed as a deviation: the consumer tests below are written after the results of configuration 3 on the input faults were known, by the same researcher, who also chose the code faults first. They cannot count as a blind test of any configuration, and the paper states this.

**Set 2, first kind, fixed now.** Five changes of unit or meaning with the schema still valid, given as exact source replacements in `experiments/p1/code-faults.json`:
- C1: evidence confidence falls as spans are added, instead of rising (`ShadowParams.cs`);
- C2: the observation's timestamp reaches the learning runtime in seconds instead of milliseconds (`ServerRuntime.cs`);
- C3: the projection stores the fingerprint and the asset version in each other's columns (`V9EventService.cs`);
- C4: the "latest" render identity returns the oldest (`V9EventService.cs`);
- C5: the observation's risk score reaches the runtime inverted (`ServerRuntime.cs`).
The plan's example of character offsets and millisecond spans cannot be given as written: no server code reads their values, only how many there are. C1 and C2 are the nearest forms.

**Consumer tests, the rule fixed now.** One test class, `ConsumerExpectationTests`, written from the consumer's code and not from the matrices' fixtures. For each component that reads an event or job, one test per thing it reads: the projection (identifiers, fingerprint, asset version, pairing status, append-only refusal); the admission check (an honest proposal is admitted, each field mismatch refused); observation dispatch (latest identity, timestamp, risk, tick and hash carried over); the evidence reader (text, hash, and confidence against span count); and the promotion worker's job parser (the fields it reads, and refusal of a malformed job). The tests' lines and writing time are recorded.

**Pre-deployment checks, per configuration.** (1) The drift matrix against its recorded baseline, and the gate matrix. (2) The drift matrix on a host with the liberal switch set, without the assertions that differ from the recorded baseline on the unmutated code, each listed in the results; and the gate matrix. (3) The consumer tests and the gate matrix. (4) The gate matrix.

**Workload.** The chain's inputs posted to the configuration: two paired traces, an observation, an honest proposal, an opinion. Only refusals and server errors count at this step: reading the stored rows would be a check that the configuration does not have. In configuration 4, the audit job runs after it and a non-empty list counts. On unmutated code every check and the workload must pass in all four, or the study stops.

**Where a code fault is not applicable, fixed now from the code.**
- Kernel schema (FU-01, 02, 06, 18) and boundary rules (FU-03, 05, 17): not applicable in 3 and 4, which use no schema at run time.
- Endpoint validation of the paper's path (FU-04, 13): not applicable in 2, 3 and 4, whose requests leave that path before it.
- Identity rules (FU-07a, 07b, 08, 11, 14): not applicable in 4, which switches them off.
- All others, the 15 reachable gate mutants and C1–C5: applicable in all four.

**Detection point and order.** The checks of the row above in order, then the workload, then the audit; the first that fails is the point. A fault that does not build is reported as such. Rows written are counted for detections at the workload or audit; a detection before deployment writes none.

**Deviations of this part (5 November 2026).** A first pass stopped at FU-07b after 12 faults, because P1-A's switches had rewritten the one line that its catalogue entry matches. The driver now gives that mutant's match for the new line, checks every match before any run and records which test failed; the pass was restarted in full. That second pass reported 15 mutants as not building, because the driver left warnings as errors and they leave unreachable code; the paper's mutation tool builds with that rule off, and the driver now does too. The pass was restarted in full again, and only the third is reported. In that first pass FU-06, a kernel-schema fault marked not applicable in configurations 3 and 4, made a consumer test fail, because the runtime still builds its proposal through the kernel's schema: the rule above is kept as fixed, and each fault's raw check outcomes are in the results.
