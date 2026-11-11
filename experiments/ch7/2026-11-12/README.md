# Chapter 7 staged research-loop development qualification

Status: **PASS_DEVELOPMENT_QUALIFICATION_ONLY**. Ten declared development cases; one C2 path; no held-out cases and no C1/C2 effect estimate. All interpretation is AI-assisted, with no independent human coding or supervisor approval inferred.

The plan `aed0795` was separately pushed before implementation. Complete attempt 01 (`080409a`) is retained as STOPPED: the version-mismatch behavior was correctly refused, but the observer wrongly expected a private reason code in the deliberately generic public HTTP error. The prospective correction `c4b384b` preceded observer implementation `3223a11`; complete attempt 02 uses that frozen code and fresh renderer/database records. It requires the generic HTTP 400 code plus a typed service diagnostic and verifies zero diagnostic writes. No case prefix is combined across attempts.

| Case | Final authority | Promotions | Round-2 executions | Observed reason |
|---|---|---:|---:|---|
| H | verified | 1 | 1 | qualified |
| I1 | unknown | 0 | 0 | execution_intent_mismatch |
| I2 | unknown | 0 | 0 | admission_refused |
| I3 | verified | 1 | 1 | qualified |
| I4 | unknown | 0 | 0 | execution_unknown |
| I5 | failed | 0 | 0 | execution_failed |
| I6 | unknown | 0 | 0 | receipt_stage_insufficient |
| I7 | revoked | 1 | 0 | qualified |
| I8 | absent | 0 | 0 | P0001: rollback after both promotion rows were present |
| S1 | verified | 1 | 1 | qualified |

H is the healthy path. I1–I8 exercise the eight declared invariants; their successful outcomes include refusal, idempotency, preserved unknown state, revocation and rollback, rather than eight statistical detections. S1 deliberately selects an allowed act inconsistent with the requested act while retaining valid identities and passing code: it is promoted and reused. This is a limit of the checks, not a detected fault or human emotion-quality result.

Each case uses the actual authenticated product perception and retrieval endpoints, archived code in the Jint sandbox, registered UDP intents, the separately implemented Godot client's closed/sealed applied-parameter file, real receipt/proposal event ingestion and promotion gates on PostgreSQL. Ten fresh owned case databases share a declared renderer session; they are constructed controls, not independent population draws. The atomic transaction covers spec/report, authority and outbox. Later perception delivery is observed separately and is not falsely included in the database transaction. The product server does not register this research adapter.

Actual loaded renderer runtime is Godot 4.5.2 .NET, managed .NET 10.0.14; client/Core hashes and loaded-module MVID bases are retained in playback/runtime records. The PMX asset differs from the historical P1-C asset and is identified by hash only; no licensed model is redistributed. Headless applied-overlay receipts do not establish displayed frames, later physics, semantic suitability or independent replication. The complete incidentally generated per-vertex skinning traces are retained locally with hashes in `additional-local-files.json`; they are not inputs to any qualification decision and are outside this parameter-stage study. All qualification-relevant raw records are public; JSONL compression preserves original bytes and records logical hashes.

Local regression: 649 passed, 20 conditional skips; 38 browser checks not enabled. The initial full regression's single MCP child-runtime failure and corrected PATH run are both retained, as are the new HTTP-fixture failures and analyzer build failure. The 18 targeted Chapter 4/authority/scope checks pass after fixing the new complete HTTP fixtures. These are engineering checks, not new P2 model judgments, formal Mac qualification or journal acceptance.

Run the standard-library verifier from a checkout:

```sh
python3 experiments/ch7/2026-11-12/verify_archive.py
python3 experiments/ch7/2026-11-12/test_rejections.py --root experiments/ch7/2026-11-12 --repo .
```

The verifier reconstructs every finite case, source/receipt binding, actual state/write/reuse counts, the semantic limit and resource records. Three disposable-copy changes must be rejected: missing case, corrupt raw bytes and positive reuse after revocation. It launches no database, renderer or model. The original archive remains unchanged. The separate top-level acceptance record pins the final manifest; it attests mechanical evidence checks only.

Remaining work: specify and freeze the C1 baseline, all checks/state/mapping/scoring and case count/order before writing a new held-out batch. Development cases are never reused as held-out material. P2 formal hardware eligibility, new public-task judgments, larger models, P3 broader corpora/maintenance/answer-quality evidence and author/institutional approval remain separate gates.
