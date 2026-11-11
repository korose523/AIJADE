# P2-A candidate task review

This packet implements the separately pushed candidate review plan cc1ff39. It follows archive fc01b9d. The source release contains 542 tasks. The fixed direct-port class contains 425. The proposed review pool contains 422 tasks and 115,185 retained cases. Every author decision is pending.

## Review files

- results/review/task-review.md gives the complete 542-row index.
- results/review/task-review.csv is the sortable author checklist.
- results/review/candidate-statements.jsonl contains the 422 proposed statements and calling contracts.
- results/review/task-decisions.jsonl records task-specific evidence and exact retained and excluded case identifiers.
- results/review/case-decisions.jsonl.gz maps all 116,753 original direct-case identities to the proposal and its reason.
- results/review/summary.json gives the denominators and all dispositions.

The 397 released tasks, 21 tasks with an explicit proposed domain filter, and four separately identified exact arithmetic variants are proposals for author reading. Mbpp/793 has only its three published base cases. The 117 non-direct tasks retain their original per-task type/comparator reason codes. Mbpp/255, Mbpp/260 and HumanEval/132 are excluded as whole tasks from this proposal. The four exact variants retain separate identities and their links to source cases.

## Mbpp/255 reference and runtime

All three base and 109 plus reference outputs are present in results/recovery/. The native unmodified CPython implementation ran one case at a time and produced the same bytes as a fresh positional-successor implementation. The two routes used the pinned CPython 3.12.14 and deserializer. Both receipts and isolation profiles are retained. The native route used 17.800 seconds wall time and 1,159,798,784 sampled peak RSS bytes under the recorded 2 GiB limit. The prior partition-wide RSS stops remain in their earlier archives.

The value stream contains 2,015,960 tuples with 153,040,920 elements. Its 6,778,031 compressed bytes store the full ordered outputs. Each cases.jsonl record has a typed alphabet, tuple arity, tuple count and byte range into the concatenated gzip stream. One byte indexes one alphabet value. The explicit tuple count distinguishes an empty result from a result containing an empty tuple. Duplicate input positions retain duplicate output tuples.

Use the streaming decoder from this directory. The preview limit bounds displayed tuples.

    python3 recover255.py decode results/recovery plus 85 --preview 1

The archived Jint executor was checked separately on each recovered case with the recorded 2,000 ms and 512 MiB allocation limits. It produced 107 passes, 1 sandbox timeout, 2 array-length errors and 2 expected-literal transport exclusions. The 64 MiB transport ceiling was fixed in the plan. The largest expected literal measures 925,704,937 bytes. The whole task is excluded from the proposed pool.

## Mbpp/260 statement

The source trace reaches Google MBPP commit f82046b. Its prompt asks for the n-th Newman-Shanks-Williams prime. Its recursive source and three examples evaluate s_0=s_1=1 and s_n=2s_(n-1)+s_(n-2). The EvalPlus adaptation computes the same recurrence iteratively. An independent companion-matrix check agrees with all 107 archived reference values.

Newman, Shanks and Williams define the special numbers at odd indices and give prime indices starting at 3, 5 and 7. Their first prime is s_3=7. Using that definition, the audit derives a lower bound for a positive rank n. The n-th prime, if defined, has index at least 2n+1. Each released s_n is smaller. This identifies 104 rank conflicts and three inputs outside the proposed one-based domain. The released examples 3→7, 4→17 and 5→41 do not implement prime rank. Recorded composite witnesses include s_6=99=9×11 and s_9=1393=7×199. The task is excluded. A future recurrence-index exercise would need its own task identity and author decision. [Original Google task](https://github.com/google-research/google-research/blob/f82046ba5aabbbb427dbfd38a254d26bff08b533/mbpp/mbpp.jsonl) [Original mathematical paper, pp. 129 and 131](https://www.impan.pl/en/publishing-house/journals-and-series/acta-arithmetica/all/38/2/102667/simple-groups-of-square-order-and-interesting-sequence-of-primes)

## Review status and subsequent stages

The source reading and case-domain decisions are AI-assisted. The 52-task semantic ledger now contains 8,528 agreements, 343 outside-domain cases and 242 statement conflicts, covering all 9,113 case identities. Every proposed domain, variant and task exclusion remains open for the author to read and decide. HumanEval/132 retains the archived 1,014-case contiguous engineering check and its 30 subsequence differences, and is excluded from this pool.

There were no model calls in this follow-up. Difficulty pilots, development/selection partition decisions, the verifier precision pilot, N/T/q and device qualification retain their planned stages. The current proposal does not assign model-development or main-run tasks. The primary model estimates will be conditional on that later task selection.

## Recheck

    python3 verify_archive.py

The audit recomputes every compact reference stream, joins all source-task and case identities, checks the independent decision counts and rejects deliberately corrupted records. The artifact receipt includes source and prior-dependency hashes. Engineering corrections are retained in results/engineering/.
