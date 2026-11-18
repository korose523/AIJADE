# Chapter 7 Mac qualification preparation

The 17 November review allows the 40-pair comparison after successful Mac
qualification. The advisor's reply to the one-page Mac qualification proposal
is pending. The proposed qualification uses the same ten known cases, with C1
and C2, in two isolated runs. It asks for agreement on every case's decisions
and complete observations without timeout or runtime error. The 40 worklist
slots are the two repeats of these known conditions. Fresh held-out construction
and measurement remain pending. Table 7.3 is `NOT_RUN`.

`worklist.json` re-derives the three historical input files byte-for-byte,
verifies the four archived program and test source hashes, and lists the
20 conditions in their original order for each repeat. These are the retained
known fixtures as of the historical input commit. The later execution will use
inputs re-derived against its own approved implementation commit.

```sh
mkdir -p .runtime/ch7-preparation
python3 -B experiments/ch7/prepare_known_repeats.py --scratch .runtime/ch7-preparation worklist \
  | cmp - experiments/ch7/mac-known-repeats-preparation/worklist.json
python3 -B experiments/ch7/test_prepare_known_repeats.py .runtime/ch7-preparation \
  | cmp - experiments/ch7/mac-known-repeats-preparation/offline-controls.json
```

The tests use the retained stopped/complete archive and deliberately labeled
synthetic packages derived from old rows. The matching and differing synthetic
packages illustrate tool behavior. No renderer, model, database
or live observer runs in either command. All earlier refused, timed-out and
engineering-only attempts remain archived with their original dispositions.

The separate `preflight_known_repeat_readback.py` readback checks the protected
source, the historical engineering Release outputs, and the exact content of
the known worklist. It records the absence of the formal decision and
publication files and lists the required acceptance inventory. It compares the
runtime and scoring inputs after rebinding the protected revision and its
dependent digest, and checks the selection without changes.

```sh
python3 -B experiments/ch7/preflight_known_repeat_readback.py \
  --protected-repo "$protected_checkout" --historical-release-manifest "$release_output_manifest" \
  --supervisor-review "$review_original" --scratch "$project_scratch" --archive-deck "$archive_deck"
```

The report lists programme sources found in the protected sparse checkout and
those verified in the separate optional archive deck. The latter is a read-only
copy of four Git objects. The future Q worktree must contain those files at
their original relative paths. The retained engineering Release build identifies
the protected revision and cannot supply the separately approved build for Q.

## After the reply

1. Record the reply and prepare the approved implementation Q and build
   publication B under [the canonical launch procedure](../mac-known-repeats-qualification/LAUNCH.md).
   Materialize the four bound programme sources in the clean Q checkout and
   preserve both repeat receipts, including any stops.
2. Run the implemented two-repeat `launch_known_repeats.py` through that
   procedure with the approved prebuilt renderer, Python 3.11 or newer, and
   psutil 7.2.2. The launcher re-derives the known input bytes against Q and
   checks the terminal block evidence before advancing.
3. Use [the acceptance procedure](ACCEPTANCE.md) to review the complete
   repeats before publishing acceptance and construction freeze. The
   [four-block procedure](../FOUR-BLOCK-EXECUTION.md) uses these bindings for
   the held-out comparison. The historical sequence and its refusal records
   retain their original scope.
4. An additional offline delivery check from the repository root takes the
   two completed **block** directories. Its
   `--expected-identity` JSON is independently archived from the approved
   pre-run materials with schema `aijade.ch7.known-repeats-expected-identity.v1`,
   a full `implementationCommit`, an `executionPlanSha256`, and the closed
   `backend` tuple declared by `finite_construction_binding.BACKEND_FIELDS`.
   A dossier copied from the observed outputs is unsuitable as the independent
   input. This tool checks supplied identity bytes and leaves approval provenance
   for review.

```sh
python3 -B experiments/ch7/prepare_known_repeats.py --scratch .runtime/ch7-preparation \
  check-delivery /project-local/repeat-1/block-1 /project-local/repeat-2/block-1 \
  --expected-identity /project-local/approved-expected-identity.json
```

The delivery checker reuses `compare_known_repeats.py`, independently re-derives
the expected known inputs, and binds the prepared handoff, registered renderer
intents, sealed state, xUnit outcome, terminal case events and owned cleanup
to each run. It reports closure and decision agreement for review. It does not
issue `QUALIFIED_BEFORE_FRESH_CASE_CONSTRUCTION`, build or start the backend,
or unlock the held-out construction. Formal acceptance observes the reply and
the prospectively frozen procedure, actual run identities, and all original raw
records. Quality of rendered pixels and device or human-review acceptance are
outside this artifact.
