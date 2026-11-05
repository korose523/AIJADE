# P1-B, follow-up: reading the surviving mutants

**Status.** Committed to this repository on its own on 5 November 2026, after the scores of `experiments/p1/independent-fault-set.json` were known and before any survivor was read. It is not registered on an external platform. By the first author's decision of 5 November 2026 it runs before the supervisor's review.

**Question.** Of the mutants that survived although the matrix executed them, how many cannot change behavior, how many change only diagnostic text, and how many change a decision or value that the matrix does not observe?

**Set.** All survivors after the hand check: 164 of the drift matrix and 193 of the gate matrix, 357 in all. Mutants never executed are not read.

**Reading.** Each mutant is read at its source line at the plan commit of the run (`9922825`) and given one category, with a reason of one clause:
- *equivalent*: no input can make the program behave differently (the plan of P1-B excludes such a mutant only with a written reason per mutant);
- *diagnostic*: changes only text or a label in a log, an exception message, an audit note or a description, which no code branches on;
- *decision*: changes a value or a branch that can reach a stored row, a response or a verdict, and the matrix does not observe it;
- *unsure*: the reader cannot place it from the code. Unsure is never counted as equivalent.

A mutant is placed in *equivalent* only if the reason holds for all inputs, not only for those the matrix uses. Unreachable from this test but reachable from other callers is *decision*.

**Reporting.** The counts per matrix, area and category. The score K/(K+S+N) and K/(K+S) with the equivalents excluded, as the plan of P1-B provides, next to the scores without exclusion, which stay the study's result. Diagnostic mutants are not excluded from any score; a score over the rest is given only as a description. Every row goes to `experiments/p1/survivor-reading.json`.

**Limits, fixed now.** One reader, Claude, who knows the scores and the code's author's aims. Nothing is run for this reading, so an *equivalent* is a judgment, not a proof. The first author must read the *equivalent* rows before the sentence that relies on them stands.
