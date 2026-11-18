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

## After the reply

1. Record the reply and freeze the approved plan, implementation, scoring and
   backend identity before starting either repeat. Re-derive the same known
   inputs through the existing `finite_inputs.py qualification` mode under that
   exact implementation commit. Use independently isolated output locations
   and preserve both terminal receipts, including stops.
2. The prospective launcher should call the finite block primitive for each
   repeat. `run_finite_block.py` expects exact `--repo`, `--client`, `--model`,
   `--selection`, `--manifest`, `--scoring`, `--output`, `--dotnet`,
   `--assembly`, `--build-manifest`, `--godot`, `--docker`, `--execution-plan`,
   `--db-container` and `--build-freeze-commit` inputs. Mac strict mode also
   needs `--implementation-commit`, `--build-freeze-path` and `--process-policy`.
   The block checks a clean source checkout, its build and policy, `psutil
   7.2.2`, `DOTNET_PROCESSOR_COUNT=2`, and `AIJADE_GIT_COMMIT`. Its caller
   supplies the Godot executable and sandbox profile as `AIJADE_REAL_GODOT`
   and `AIJADE_GODOT_SANDBOX_PROFILE`, an owned `AIJADE_FINITE_TIMERS_FILE` and
   the relevant lifecycle context and sequence clock. The finite primitive
   requires Python 3.11 or newer and an already-built renderer.
3. Approve the new launch path explicitly after the reply. The current plan
   dispatch recognizes four historical Mac execution plans. A different
   filename falls through the legacy path. The historical sequence launcher
   uses its own 600-second settling and 120-second admission, and the old
   acceptance reader binds one P4-era sequence. These frozen paths remain
   historical. A new two-repeat launcher and a prospective construction
   acceptance binding are still required after review.
4. After the future two repeats have closed, use the offline delivery check
   from the repository root with the two **block** directories. Its
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
