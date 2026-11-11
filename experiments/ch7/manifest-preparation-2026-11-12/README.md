# Identifier-independent scoring preparation — no new experiment

Prospective plan `c75df8e` preceded implementation. This packet derives only from
the complete paired development measurement archived at `8de976772e76`; it adds
no model output, renderer execution, new case or held-out observation. The ten
known cases are re-encoded under arbitrary identifiers and fully reordered.
Nested source trace identifiers remain visible: this is not investigator blinding.

The new scorer accepts a closed case/window manifest rather than requiring
H/I1–I8/S1. IDs are lookup keys. Manifest class/window/allowance definitions come
from the unchanged frozen window registry; the scorer receives no expected C1/C2
outcome. All twenty original per-case records and both complete arm summaries
agree with the unchanged frozen scorer, including legal first duplicate actions,
pre-revocation promotion, absent memories and transient service success before
rollback. The original measured packet and all its failures remain unchanged.

Eighteen instrument tests also exercise adversarial controls: arbitrary aliases
and ordering, ignoring expected/qualification flags, adverse C2 outcomes, a
reversed comparison, incomplete/absent captures, malformed/missing/duplicate
identities and values, changed denominators and stage allowances, orphaned rows,
and a repeated existing normal record. The last control demonstrates support for
counts other than ten; it is explicitly synthetic and adds no empirical data.

**Normal-completeness clarification during implementation.** Synthetic partial-row
checks showed that the legacy normal-acceptance heuristic did not require its
report to exist or point to its spec. The new interface explicitly classifies
such a normal trace as incomplete. Its primary integrity-window counts retain
the frozen definitions, while orphan spec/report diagnostics are separately
reported. This clarification was made during instrument development, after the
initial 16 controls passed and before any new cases were constructed; two added
controls bring the final suite to 18. Both observed normal traces and every other
original measured score remain unchanged. No historical scorer/data was rewritten.

`source-freeze.json` binds 331 actual source/dependency/adapter/input files to
public commit `8de976772e7635af7719fba8b76716f8cdb7a482`, with SHA-256 and Git
blob identities. It covers all tracked `src` files plus the actual research
adapter, legacy drivers, frozen window scorer/layout and selected candidate input.
This is a reproducibility binding, not a formal Mac qualification or approval.

The later [held-out proposal](../heldout-protocol-proposal-v1.json) is **not
approved and NOT_RUN**. It proposes 40 pairs / 80 rows in four ten-pair blocks,
four normal, four semantic-limit and four cases in each of eight integrity
families. The proposed 28 promotion / 32 reuse windows per condition are a finite
mechanism-coverage budget, not observations or a power claim. Four constructed
variants in one family are not four independent fault families.

The manifest-driven **live** driver, reviewed case-construction rules, genuinely
new concrete cases and formal protocol/count/backend review remain open. The
legacy live driver still branches on the ten development labels. No future case
generation seed, author approval, supervisor approval, independent human review
or held-out completion is inferred from this preparation. Thesis Table 7.3 stays
empty. All interpretation and controls are AI-assisted.

Run from the repository root:

```sh
python3 experiments/ch7/manifest-preparation-2026-11-12/verify_archive.py
```

The check verifies all packet bytes, every pinned source, exact derivation from
the old complete observations, both full scorer outputs and all instrument tests.
