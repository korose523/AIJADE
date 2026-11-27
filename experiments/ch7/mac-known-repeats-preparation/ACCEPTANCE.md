# Mac known-repeat evidence and construction binding

Qualification awaits the supervisor’s reply. The implemented acceptance reader
prepares and verifies file identities. The offline controls use synthetic
records. No real qualification was issued and no held-out case was constructed.

(Added 27 November 2026: the supervisor approved the two-criterion qualification
standard on 21 November 2026 and accepted the qualification on 23 November 2026,
on a condition met the same day; the review of 27 November 2026 keeps both. See
[`../README.md`](../README.md). The paragraph above keeps the state of 18 November 2026.)

## Freeze and run after the reply

Use the successor prefix `experiments/ch7/mac-known-repeats-qualification/`.
The approved implementation commit Q includes the executable plan and a
`decision.json` with the following fields.

| Field | Required value |
| --- | --- |
| `schema` | `aijade.ch7.known-repeat-decision.v1` |
| `status` | `SUPERVISOR_REPLY_CONFIRMED` after the actual reply |
| `executionPlanPath` and `executionPlanSha256` | Exact plan path under the prefix and its bytes at Q |
| `qualificationPlanSha256` and `replySha256` | Exact approved one-page plan and received reply digests |

Retain the actual reply privately and obtain the expected digest independently
of the run bundle. The launcher checks those bytes and the frozen backend before
it starts. The Git records contain the digest. The actual reply stays private.
A digest ties identity to captured bytes. The authenticity and scope of the
received reply still require human verification.

Build publication B descends from Q and records the actual compiled build in
`frozen-build.json` under the same prefix. Both approved known-condition repeats
use the same Q, B and backend. The launcher keeps both outcomes even if one
does not complete. The accepted path requires actual launcher origin, distinct
repeat identities, complete flow and renderer outcomes, process and database
cleanup, and agreement on all 20 casewise decisions.

## Evidence review and held-out construction

Run the read-only inspection against the completed, project-local launch
directory. Supply the digest of the independently captured approval record.
The path names below describe arguments to fill from actual run evidence.

```sh
python3 -B experiments/ch7/known_repeat_acceptance.py --repo . \
  --implementation "${IMPLEMENTATION_COMMIT}" inspect \
  --evidence-directory "${KNOWN_REPEAT_DATA}" \
  --trusted-approval-sha256 "${APPROVAL_SHA256}"
```

The inspection replays the delivery checker and gives an evidence inventory with
byte sizes and SHA256 digests. It independently checks both scoreable runs and
returns `READY_FOR_QUALIFICATION_ACCEPTANCE_REVIEW` only for a complete,
matching, production-marked pair. The inspection cannot publish acceptance.

After review, acceptance publication A adds the exact inventory files under
`qualification-evidence/` and the canonical `qualification-acceptance.json`.
The acceptance object uses schema `aijade.ch7.known-repeat-acceptance.v1`, status
`QUALIFIED_BEFORE_FRESH_CASE_CONSTRUCTION`, the fields `implementationCommit`,
`acceptedAt`, `approvalSha256`, `buildFreezeCommit`, `qualifiedBackend` and
`evidence`. Copy the backend and the manifest from the inspected bytes. The
acceptance timestamp must follow both original terminal timestamps. The
constructor opens the exact Git objects at A and replays the checks on them.

After A, draft the separate freeze publication using the observed backend and
the source closure at Q.

```sh
python3 -B experiments/ch7/known_repeat_acceptance.py --repo . \
  --implementation "${IMPLEMENTATION_COMMIT}" draft-freeze \
  --acceptance-publication "${ACCEPTANCE_COMMIT}" --acceptance-sha256 "${ACCEPTANCE_SHA256}" \
  --frozen-at "${FROZEN_AT_WITH_TIMEZONE}"
```

Publish this object at `construction-freeze.json` under the prefix in a separate
descendant commit. The normal constructor and runtime preflight use
`construction-binding.json` with schema
`aijade.ch7.known-repeat-construction-binding.v1` and the exact fields
`implementationCommit`, `acceptancePublicationCommit`, `acceptanceSha256`,
`constructionFreezePublicationCommit` and `constructionFreezeSha256`.
The constructor validates the references before invoking the held-out derivation.
The measurement preflight recollects the actual backend files and compares
them with the frozen backend. Historical implementation commits retain their
original acceptance rules.

```sh
python3 -B -m unittest discover -s experiments/ch7 -p test_known_repeat_acceptance.py -v
```
