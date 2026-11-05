# P1-C: Do the evidence gate's guarantees hold on receipts from a separately developed renderer?

**Status.** Committed to this repository on its own on 6 November 2026, before its code and before the first session. It is not registered on an external platform. By the first author's decision of 5 November 2026 ("run on the Mac first") and of 6 November 2026 ("run P1-C as proposed") it runs on the Mac before the supervisor has seen it; the three choices the draft reserved for the supervisor were made by the first author on 6 November 2026, not by the supervisor. Sections "Fixed on 6 November 2026" and "Group 3: expected outcomes" below govern where they differ from the draft's text.

*Authors: Zexiao Weng, MinPo Jung (corresponding).*
*Last revised: 4 November 2026. Code statements checked against commit `97aab7c` of the code repository and MOSAIC revision r647 (the desk check at the end of this file was made at `eaa6cf4` and MOSAIC on 1 November; the files it names are unchanged since).*
*Revisions: 1 November 2026 (drafted from plan v0 §5.9 and the planned Section 4.10.3 of the dissertation, with a read-only desk check of both code bases; the Chapter 4 external comparison the supervisor asked for, review of 24 October 2026, §2.3 (6)); 3 November 2026 (supervisor's review: the client is named as a separate implementation by the same researcher, not an independent replication, and the results say which parts test the client itself); 4 November 2026 (the last row of the desk check: the documentation had already been corrected in `eaa6cf4`); 6 November 2026 (feasibility probe added at the end of this file; the plan's text above is unchanged).*

## Study information

**Research question.** The paper's §3–§4 claim that a learning proposal is admitted only against a real, paired render receipt whose parameter fingerprint and asset version it repeats, and that drifted or tampered render events are refused without writes. Do these guarantees hold when the receipts come from a separate renderer implementation by the same researcher, the native MikuMikuDance (MMD) client of the author's MOSAIC project, which runs on the Godot engine and implements this system's external renderer contract? This is not an independent-team replication.

**Hypotheses.** None. If the client implements the contract as specified, every case taken from the paper should have the outcome the paper recorded for it on the author's server, and every new case of group 3 its expected outcome; any difference is reported as found.

## Design plan

**Study type.** Experiment on software (no human participants).

**What the receipts can show (fixed now).** The client writes `aijade-render-state.jsonl` line by line as it renders (schema `mosaic-render-state-log-v2`, read from the MOSAIC source on 1 November 2026).
- The header names the schema, the two stages, the hash rule and `presented_frame_observed: false`, and identifies the session: a renderer context id that is new for each session, the SHA-256 of the model file and of the first clip, the session id, the start time and the behavior plan's SHA-256, seed and port.
- Rows of stage `behavior_overlay_pre_solve` list the packets consumed (each with its `trace_id`, which is the AIJADE intent id) and the morph and bone values the behavior overlay applied before morph evaluation, joint limits, inverse kinematics and physics, with `missing_keys`, `unmapped`, `conflicts` and the renderer's `applied_params_hash`.
- Rows of stage `post_solve_pre_skinning` give, for the same frame, the bones after the solvers and the morph weights passed to morph evaluation.
- The end record gives the number of earlier lines and their SHA-256. A file without it belongs to an unfinished session.

No row observes a displayed frame. The receipts can therefore support "the behavior parameters were applied" (pre-solve rows) or "the solved pose before skinning had these values" (post-solve rows), not "a frame was displayed". This study imports only pre-solve rows as receipts, which is also all that this system's reader of the file (`RenderStateReceipts`) reads today; post-solve rows are reported descriptively.

**Design (plan v0 §5.9).** The closed loop is staged:
1. before each intent is sent to the client (`MosaicRendererLink`, UDP on the loopback interface), its id, its request event and its session are written to an intent registry (new code);
2. the session ends and the client closes its file with the end record;
3. a sealed manifest (session and renderer instance, end state, expected and actual counts, file SHA-256, completion marker) is checked against the file's header and end record and against the registry;
4. only then are receipts imported: each pre-solve row whose consumed `trace_id` is a registered intent becomes an `aijade.lpm.render_ready` event, paired by trace with that intent's `aijade.persona.render_requested` event, through the same HTTP boundary as every other event.

Identity is bound through the registry and never inferred from the latest receipt. The two parameter hashes, the renderer's (keys sorted, values in six decimals, SHA-256) and this system's canonical-JSON hash, are each recomputed from the row's values by their own algorithm and are never compared with each other. The study supports conclusions about receipts checked after a session has ended, not about blocking an action while it runs.

The registry, the sealing check and the importer are plan v0's work package WP04 (execution evidence), which Chapter 7's integration test shares: the binding of session, context, intent and version (WP04-02), the two hashes and the stage (WP04-03), the completion of the receipt file and the time of import (WP04-04), and the link to events and the promotion gates (WP04-05).

**From a row to a receipt event (fixed now, except where marked).**
- `intent_ref`: the registered intent id that the row's `trace_id` names.
- `render_ref`: the renderer context id and the row's `seq`, joined by a colon; it is unique because the client creates a new file and a new context id for every session.
- `applied_params_hash`: this system's canonical-JSON hash of the row's applied values (`morph.*`, `bone.*`), the same function the product's own render reporter uses.
- `asset_version_hash`: the header's model digest alone (`pmx_sha256`).
- `session_id`: the session recorded in the registry.
- The idempotency key of both events is derived from `render_ref`, so that importing a file again writes nothing new.

**Cases (fixed now).** Three groups. Groups 1 and 2 repeat cases that the paper ran on the author's server with receipts constructed by its tests; here the client's receipts take their place, and each outcome is compared with the one the paper recorded. Before that comparison, the paper's drift-matrix and admission-check tests are run unchanged at this study's code commit, and their outcomes must equal the recorded ones. Group 3 is new and exists only for file receipts; each of its cases is compared with its expected outcome.
1. *Contract drift on the receipt topic.* The seven case groups of the drift matrix on `aijade.lpm.render_ready` (26 of its 287 assertions): valid payload; asset version absent; blank parameter hash; blank asset version; blank or missing render reference; unknown field. The client's receipt supplies the valid payload. The request topic belongs to this system and is not varied.
2. *Tampering.* The honest proposal and the five tampered ones of the admission checks against stored traces built from the client's receipts: a render that does not exist; an unpaired trace; a forged parameter fingerprint; a forged asset version; a self-reference.
3. *Sealing and import (new; expected outcomes written before the first session).*
   - Sealing: a file without an end record; an end record whose line count or digest does not match (truncated or altered file); a file in the old format (`MOSAIC_RENDER_STATE_LOG=v1`: rows only, no header or end record); a header whose renderer context or session does not match the manifest; a client restarted during a session (the first instance's file has no end record, and the second instance's renderer context is not the one the manifest names); a file from an earlier session; a row whose `trace_id` is not registered; a registered intent with no row; a row whose renderer hash does not recompute from its values. None of these may produce a receipt event. A registered intent left without an importable receipt is counted as unknown, not as refused and not as a failure of the renderer.
   - Import: the same sealed file imported twice (the second import writes nothing new); an import stopped part-way and run again (each receipt is written once).

**Qualification of the client (fixed now).** The client is qualified for this study when, in one healthy session at the recorded MOSAIC revision:
- the conformance test against the client's own parser passes (every packet for the eleven dialogue acts translates without rejection or unmapped field);
- the file is schema v2 and is closed by an end record whose count and digest verify;
- every row's renderer hash recomputes from its values;
- every registered intent has a pre-solve row.

If the client cannot be qualified, the comparison is reported as not done, with the reason; tests that only parse the schema are not used in its place (plan v0 §5.9).

**Running the client.** The client is built and run inside the MOSAIC repository at a revision recorded in the results, with the author's consent and under MOSAIC's own rules; MOSAIC's code is not changed for this study. The sender and the client run on one machine, as the contract's transport is the loopback interface: the Mac. This system's stage relay to MOSAIC's workbench (ADR-002) stays off during the sessions.

**Blinding.** None (automated).

## Sampling plan

**Existing data.** None; all outcomes come from new sessions.

**Sessions and intents (fixed now, except where marked).** Three rounds (see below). In each session one intent per dialogue act (eleven), in a fixed order, through the deterministic mapping of `AijadeRendererPackets` (the same intent always gives the same packets).

**Sample size and stopping rule.** Each case is run once per session; its outcome is deterministic on a freshly migrated database. No stopping rule.

## Variables

**Manipulated.** Case group (drift, tampering, sealing and import). The receipts come from the client throughout; the comparison is with the outcomes the paper recorded and with the expected outcomes of group 3.

**Measured.**
- Per case: accepted or refused, the reason code, whether anything was written, and whether the outcome equals the paper's recorded outcome (groups 1 and 2) or the expected outcome (group 3).
- Per session: intents registered, pre-solve rows, receipts imported, and intents left unknown with their reasons (the denominators of accepted, refused and unknown, plan v0 WP08-03).
- Descriptive: post-solve rows per pre-solve row, and the `missing_keys`, `unmapped` and `conflicts` the client reports.

## Analysis plan

**Statistical models.** None. The cases are finite and constructed; no rate over a population of receipts is estimated.

**Reporting.** The table of Section 4.10.3 of the dissertation (case group, cases, same outcome, different outcome, reason codes of differences) and, per session, the denominators of accepted, refused and unknown. The results state which parts test the client itself, namely its qualification, the mapping from rows to receipt events and group 3, and that groups 1 and 2, whose variants are built from the client's healthy receipts, mostly re-test this system's server checks.

**Inference criteria (fixed in advance).**
- Every case of groups 1 and 2 has the outcome the paper recorded, and every case of group 3 its expected outcome: the guarantees of §3–§4 held on this client's receipts for these cases. The claim is limited to one separate implementation by the same researcher at the recorded revision, the stage "behavior parameters applied" and constructed cases.
- Any difference is reported with its reason code and is not explained away. A case that the paper recorded as refused but that is admitted with the client's receipt is reported as a gap in the contract or the importer; the reverse is reported as a check that the client's receipts do not meet. A sealing case that produces a receipt event is reported as a gap in the sealing check, and an import case that writes a receipt twice as a gap in the importer.
- The paper's drift-matrix or admission-check test does not reproduce its recorded outcomes at this study's code commit: the comparison is not made until the cause is found and reported.
- The client is not qualified: the requirement stays open (plan v0 §5.9).

**Data exclusion.** None. A case that cannot be built from the client's receipts is reported as not applicable, with the reason.

**Missing data.** A session that crashes is kept: its file has no end record, so it is reported as an unfinished session, and one further session is run in its place.

## Other

**Code version.** The registry, the sealing check, the importer and their tests are committed together before the first session. They are new files beside the renderer link (`src/Aijade.Integrations/Renderer/`, a research object of Chapter 4, so the change is recorded under the project's scope rules and the Chapter 4 regression is re-run) and a new test file. Until the runs of P1-A and P1-B are archived they do not change the files those studies measure: the event boundary and kernel schemas, the event service, the promotion service and its gates, the two matrix tests and the drift baseline. Runs set `AIJADE_GIT_COMMIT`; the results file records this plan's commit, the code commit and the MOSAIC revision.

**Plan and record.** This plan is pushed to the code repository on its own and sent to the supervisor as a PDF before its code is written.

**Resources.** The machine chosen above with the client built in its repository; local PostgreSQL (recreating the local database container needs a container image download, permission required). No language model, no paid service. Scheduled with P1-A and P1-B, 15 February to 19 March 2027 (plan v0, WP08-03).

**Deviations.** Any change after registration is listed with its date and reason in the results file and the dissertation.

## Desk check (1 November 2026)

Read-only: AIJADE-next at `eaa6cf4`, the MOSAIC working copy on this Mac; nothing was built or run.

| Point | What the code does | What the plan writes |
|---|---|---|
| Receipt file | MOSAIC `host-dotnet/Mosaic.Scene.Core/RenderStateLog.cs`: schema `mosaic-render-state-log-v2`; header, rows, and an end record with the line count, the SHA-256 of the earlier lines and `complete: true`; every row is flushed as written; the file is created with `FileMode.CreateNew`, so an earlier session's file is never overwritten | Only v2 files are imported; the end record is checked before import |
| Old format | MOSAIC `clients/godot-scene/Main.cs`: `MOSAIC_RENDER_STATE_LOG=v1` keeps the old file, rows only, written when the session is saved | A v1 file is a sealing case |
| Header identity | `Main.cs`: renderer context id (a new GUID per session), model SHA-256, first clip SHA-256, session id (from `MOSAIC_SESSION_ID`, may be empty), start time; `BehaviorDriver.OpenLog` adds the behavior plan's SHA-256, seed and port | `render_ref` uses the context id; the manifest checks context and session |
| Rows | `clients/godot-scene/BehaviorDriver.cs` (`ReportFrame`, `ReportSolved`): one pre-solve row after the overlay that first shows newly consumed packets, listing each consumed packet's `trace_id`, then the same frame's post-solve row; at most 200,000 rows per session, after which rows are not written | Rows are matched to intents by `trace_id`; the cap is far above the study's intents |
| Reader | AIJADE-next `src/Aijade.Integrations/Renderer/MosaicRendererLink.cs` (`RenderStateReceipts`): reads only pre-solve rows, skips the header, post-solve rows and end record, and does not check the end record; `RendererHash` recomputes the renderer's hash | The sealing check is new; the reader is not changed |
| Receipt events | `src/Aijade.Server/V9/V9EventService.cs`: a receipt (`aijade.lpm.render_ready`: session, render reference, parameter hash, optional asset version) is paired by trace with a request (`aijade.persona.render_requested`: session, persona snapshot, intent); a receipt without a request is accepted and logged as a visible pairing gap; an intent or render reference equal to an envelope identifier is refused as a self-reference | The importer posts both through the boundary; a receipt is imported only for a registered intent |
| Own receipts | `src/Aijade.Client/Chat/Orchestrator.cs` (`RenderReporter`): posts request and receipt together after rendering, with `render_ref` `rr_<intent>` and the canonical-JSON hash of the applied parameters (`JsFormat.ContentHash`, `src/Aijade.Core/Js/JsFormat.cs`) | The same hash function for the client's receipts; the registry, unlike this reporter, is written before sending |
| Drift matrix | `tests/Aijade.Tests/Golden/p1/contract-drift.txt`: 287 assertions, 49 on the two render topics, 26 of them on the receipt topic in seven case groups | Group 1 |
| Tampering | `tests/Aijade.Tests/AdmissionChecksTests.cs`: an honest proposal and five tampered ones (`render_ref_not_found`, `intent_ref_missing`, `applied_params_hash_mismatch`, `asset_version_hash_mismatch`, `self_reference`) | Group 2 |
| Conformance | `tests/Aijade.Tests/RendererLinkTests.cs`, opt-in with `AIJADE_MOSAIC_CORE_DLL`: every packet for the eleven dialogue acts (`DialogueAct`, `src/Aijade.Memory/Development/Pef.cs`) translates without rejection or unmapped field | Part of the qualification |
| Documentation | `docs/MOSAIC-RENDERER.md` said the file is written at the end of a session; corrected to schema v2 in `eaa6cf4` | Nothing further |

## Feasibility probe (6 November 2026)

Made at the author's request, to find out whether the Mac can run the client. It precedes the code this plan calls for, none of its output is study data, and it must be disclosed with the results because it showed the format of real files before group 3's expected outcomes were written. No registry, sealing check, importer or case was run.

**Setup.** The Mac (x86_64, 8 CPUs, 16 GB, three MOSAIC research containers running). Godot 4.5.2 .NET edition already installed at `~/.local/share/mosaic/godot-4.5.2`; .NET SDK 8.0.425; nothing downloaded. Sources copied to `~/p1c-mosaic` (`clients/godot-scene`, `host-dotnet/Mosaic.Scene.Core`, `host-dotnet/Mosaic.Scene.Bullet`, the launcher, `configs/scenes`), so nothing was built or written inside the MOSAIC repository. Last-changed revisions: `Main.cs` r647, `BehaviorDriver.cs` r614, `RenderStateLog.cs` r341, `AijadePackets.cs` r4, launcher r648. Headless, MOSAIC's calm companion preset (seed 7, 40 s), the author's local PMX model (only its hash is recorded). The sender was a throwaway script, not `MosaicRendererLink`: eleven intents, one per second, each one affect and one pose packet, with made-up values.

| Check | Normal session | Session killed after the last intent |
|---|---|---|
| Client builds offline | 0 warnings, 0 errors | same build |
| Conformance test against the built parser (`RendererLinkTests`, code `6d85e4a`) | 5 of 5, none skipped | not repeated |
| File schema | v2 | v2 |
| End record | present; count and digest verify | absent, as the plan expects |
| Pre-solve and post-solve rows | 11 and 11 | 11 and 11 |
| Renderer hash recomputes from the row's values | 11 of 11 | 11 of 11 |
| Intents with a pre-solve row | 11 of 11 | 11 of 11 |

**What it changes in this plan (each to be fixed before the first session).**
1. *Where the client runs.* The plan says inside the MOSAIC repository; the launcher rebuilds the client there, and MOSAIC's own scene loads that binary. A copy at recorded revisions keeps MOSAIC read-only. Proposed: the copy, recorded as a deviation.
2. *Which machine.* The open choice can be the Mac. Proposed: the Mac; headless, since the reported stage is before skinning.
3. *What ends a session.* A session with live events ends by itself at the behavior plan's last tick, and that is what writes the end record. The behavior plan is therefore part of the design: its profile, seed and duration must be fixed.
4. *What a fingerprint covers.* A row's applied values are the whole overlay, including idle stance, fingers and breathing, not only what the intent caused. `applied_params_hash` therefore fingerprints the frame's overlay, and a receipt shows that a frame consumed the intent, not that each value came from it. The results must say so.
5. *Two intents in one frame.* A row can list more than one consumed packet (the two packets of one intent already share a row), so two intents could share a `render_ref` and an idempotency key. Proposed: a fixed pace of one intent per second, and a row naming two registered intents counts as unknown for both.
6. *Field name.* The model digest in the header is `pmx_sha256`.

## Fixed on 6 November 2026

These follow from the feasibility probe above and were fixed before any code of this study and before the first session. Each is a departure from the draft of 4 November 2026, and the results list them as deviations.

1. **Where the client runs.** Not inside the MOSAIC repository: its launcher would rebuild the binary that MOSAIC's own scene loads. A fresh copy of `clients/godot-scene`, `host-dotnet/Mosaic.Scene.Core`, `host-dotnet/Mosaic.Scene.Bullet`, `scripts/run-native-mmd-scene.py` and `configs/scenes` is made at the start of the run and built there. The results record each file's last-changed revision and a SHA-256 over the copied sources.
2. **Machine and mode.** The Mac (x86_64, 8 CPUs, 16 GB), headless, at low priority, beside whatever MOSAIC containers are running. The receipts' stage is before skinning, so no display is needed. This also means no frame is drawn, and the results say so.
3. **Behavior plan.** MOSAIC's calm companion preset (`tools/make_companion_preset.py --profile calm --seed 7 --duration-s 40 --preserve-signed`), generated once and used for every session; its files are archived. A session with live events ends by itself at this plan's last tick, and that is what writes the end record.
4. **Model.** The author's local PMX model; only its SHA-256 is recorded and archived.
5. **What a fingerprint covers.** A row's applied values are the whole behavior overlay, including idle stance, fingers and breathing, not only what the intent caused. A receipt therefore shows that a frame consumed the intent and which overlay values that frame had, not that each value came from the intent. The results state this limit.
6. **Pace and rows.** One intent per second. The receipt of an intent is the first pre-solve row that names it, as in `RenderStateReceipts`. A row naming two different registered intents makes both unknown (reason `two_intents_in_row`), even if one of them appears again later. This case was added after the probe, and is not expected in a healthy session.
7. **Rounds.** Three rounds. Each has four real client runs, with a session id of its own: healthy (`p1c-rN`), killed with SIGKILL one second after the last intent (`p1c-rN-killed`), the old format under `MOSAIC_RENDER_STATE_LOG=v1` (`p1c-rN-v1`), and restarted (`p1c-rN-restart`: SIGKILL after intent 5, a new client with a new output directory takes intents 6 to 11). Intents are `pi_<session>_<nn>`, one per dialogue act in enum order, built by `Pef.BuildPerformanceIntent` with no expressive state, sent by `MosaicRendererLink`.
8. **Row-level sealing cases.** The draft says none of the sealing cases may produce a receipt event. For the three that concern one row or one intent, this is read as: no receipt event for the affected row or intent; the file's other receipts are imported. A file-level failure writes nothing at all. This reading was fixed before the first session.
9. **Where the code lives.** The registry, sealing check and importer in `src/Aijade.Integrations/Renderer/`. The sender, the cases and the results run as opt-in tests in `tests/Aijade.Tests`, since `tools/` on the research line may not reference this module. `experiments/p1/external_renderer_driver.py` starts the client and calls them. Nothing else changes; P1-A and P1-B are archived, so the condition in "Code version" holds.
10. **Plan and record.** This plan is committed locally before its code. It has not been sent to the supervisor; the draft's sentence on that is not met, and the results say so. The first author tells the supervisor personally.
11. **Disclosure.** The feasibility probe showed real files before the outcomes below were written. Its author also writes the sealing check, the importer, the expected outcomes and the cases: nothing here is blind.

## Group 3: expected outcomes

Written before the first session and before the sealing check exists. File-level cases write zero events. In the cases of constructed variants, the variant's end record and manifest are recomputed where the column says so, so that the case reaches the check it names. "Written" counts receipt events of the variant's 11 intents; every registered intent without a receipt counts as unknown.

| Case | Input | Consistent end record and manifest? | Expected reason (must be among those reported) | Receipts written | Unknown |
|---|---|---|---|---|---|
| S1 no end record | real file of the killed session | manifest says `unfinished` | `end_record_missing` | 0 | 11 |
| S2a truncated | healthy file without its last 3 rows, end record kept | manifest yes, end record no | `end_count_mismatch` | 0 | 11 |
| S2b altered | healthy file with one value changed, end record kept | manifest yes, end record no | `end_digest_mismatch` | 0 | 11 |
| S2c altered after sealing (added) | as S2b with the end record recomputed, original manifest | end record yes, manifest no | `file_digest_mismatch` | 0 | 11 |
| S3 old format | real file of the v1 session | manifest of that session | `not_schema_v2` | 0 | 11 |
| S4a other renderer context | healthy file, manifest naming another context | no | `renderer_context_mismatch` | 0 | 11 |
| S4b other session | healthy file, manifest and registry of another session id | no | `session_mismatch` | 0 | 11 |
| S5a restart, first instance | real first file of the restarted session | manifest names the first context | `end_record_missing` | 0 | 11 |
| S5b restart, second instance | real second file of the restarted session | manifest names the first context | `renderer_context_mismatch` | 0 | 11 |
| S6 earlier session | the previous round's healthy file with this round's manifest and registry | no | `session_mismatch`, `renderer_context_mismatch` | 0 | 11 |
| S7 unregistered trace | one row's `trace_id`s replaced by an unregistered id | yes | row refused: `trace_not_registered` | 10 | 1 (`no_row`) |
| S8 intent with no row | one pre-solve row and its post-solve row removed | yes | intent unknown: `no_row` | 10 | 1 |
| S9 hash does not recompute | one value in one row changed, its renderer hash kept | yes | row refused: `renderer_hash_mismatch` | 10 | 1 |
| S10 two intents in a row (added) | a row also names the next intent | yes | `two_intents_in_row` | 9 | 2 |
| S11 manifest not complete (added) | healthy file, manifest without its completion marker | no | `manifest_not_complete` | 0 | 11 |
| I1 imported twice | healthy file, sealed | yes | second import writes nothing new | 11, then 0 | 0 |
| I2 stopped part-way | import stopped after 9 posts (between a request and its receipt), run again | yes | each event written once | 11 in all | 0 |

## What runs at this study's commit

Before any comparison: `ContractDriftMatrixTests` and `AdmissionChecksTests`, unchanged. Group 1 compares its 26 assertions with the 26 lines of `tests/Aijade.Tests/Golden/p1/contract-drift.txt` on the receipt topic, by assertion text and verdict, leaving out the row counts in brackets, which depend on the order of the matrix. Group 2 compares with the five refusal codes and the admission of the honest proposal. Group 1 and 2 use the first healthy receipt or receipts of each round; the unpaired trace of group 2 is a client receipt whose request is not posted.
