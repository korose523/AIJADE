# Chapter 7 four-block execution

Table 7.3 remains `NOT_RUN`. The planned study has 40 pairs and 80 condition
records across four ordered blocks. The Mac qualification requires the
supervisor's reply to the one-page plan. Start the held-out construction only
after the two known-condition repeats have passed and their actual raw
deliveries have been accepted. Keep every earlier refusal with its receipt.

## Qualification and build freeze

In the approved clean POSIX worktree under the AIJADE workspace, designate the
source commit as Q. Q contains the approved decision, prospective qualification
execution plan, and the measurement, construction and analysis source. Keep the
exact private supervisor reply and reviewed qualification plan under AIJADE.
Build the test assembly and its dependencies outside the worktree using Q.
Run the manifest producer with project-local absolute paths and an independently
verified Q identifier.

```sh
python3 -B experiments/ch7/freeze_known_repeat_build.py \
  --implementation-commit "$q" --assembly "$built_assembly" \
  --original-reply "$private_reply" --qualification-plan "$reviewed_plan"
```

The producer checks the approved Q decision and the original hashes, then
records every regular file in the assembly directory. Commit the generated
`experiments/ch7/mac-known-repeats-qualification/frozen-build.json` alone as B.
The canonical write is exclusive and uses a hard link to publish the completed
bytes. A filesystem failure leaves the pending file for inspection. The
launcher uses B and checks the actual assembly directory against it again.

Run the [two-repeat launcher](launch_known_repeats.py) from the approved Q
checkout, using the reviewed execution-plan hash, B, the private approval files
and a fresh output directory. Preserve every terminal receipt. The independent
[acceptance tool](known_repeat_acceptance.py) `inspect` command requires the
original raw delivery and the independently pinned approval. Publish an accepted
qualification as A, with the full evidence closure in the canonical qualification
directory. Produce and publish the separate construction freeze CF using
`draft-freeze` with the exact A commit and acceptance digest before creating
fresh inputs. A refused or incomplete qualification stops this sequence.

## Freeze the constructed inputs and measurement plan

Use [finite_inputs.py](finite_inputs.py) and [finite_validate.py](finite_validate.py)
with the successor construction binding. Keep the four runtime and scoring
manifests, binding and suitability receipt together. Publish them after CF as D,
with an `aijade.ch7.mac-data-publication.v1` manifest that lists every path added
since Q, including B, A, the A evidence closure, CF, the new input bundle, the
measurement plan, and the data-publication manifest itself. Added files are
regular, nonexecutable data. Keep Q's candidate bank and executable files intact.

The D measurement plan uses schema `aijade.ch7.heldout-measurement-plan.v1` and
purpose `confirmed_finite_heldout`. It records `implementationCommit`,
`inputsPath`, `constructionBindingSha256`, `buildFreezeCommit`,
`qualifiedBackendSha256`, `blocks`, `pairsPerBlock`, `conditionsPerBlock`,
`databasePort`, the `toolsSha256` map and the `watchdog`. Use the independently
reviewed measurement settings and their exact types from
[validate_runtime_settings](launch_known_repeats.py). Freeze the plan in D and
retain its digest independently of the execution checkout.

## Run the ordered blocks after the freeze

Use a clean checkout of D, absolute local paths, the bound Mac backend, and a
fresh project-local output directory outside the checkout. Use the path-only
configuration schema from the two-repeat launch and the independently frozen
plan digest.

```sh
python3 -B experiments/ch7/launch_heldout_blocks.py \
  --implementation-commit "$q" --expected-plan-sha256 "$measurement_plan_sha" \
  --inputs "$published_inputs" --data-publication-manifest "$publication" \
  --measurement-plan "$measurement_plan" --config "$local_config" \
  --output "$fresh_attempt"
```

Each child rechecks the tracked bytes, approved build, backend and prior
verified evidence. The parent advances only after closure of the scheduled
process and the original terminal, a full block audit, and matching receipts.
Stops preserve the completed prefix and the attempted block's available raw
evidence. The independent sequence scorer uses the four complete block
directories. The launcher does not synthesize missing conditions.

## Reproduce the offline controls

```sh
python3 -B -m unittest discover -s experiments/ch7 -p test_freeze_known_repeat_build.py -v
python3 -B -m unittest discover -s experiments/ch7 -p test_heldout_audit_route.py -v
python3 -B -m unittest discover -s experiments/ch7 -p test_four_block_end_to_end.py -v
```

The end-to-end control uses isolated Git objects and labeled synthetic raw
deliveries. It validates the shared closure and scoring path at a controlled
backend interface; separate controls exercise the frozen resource policy.
Neither test invokes the actual Mac backend or creates formal research inputs.
