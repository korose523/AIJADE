# P2-R recorded-label statistics

The P2-R comparison plan calls for the archived and regenerated populations to be reported side by side. The read-only reporter binds the three complete recorded groups to the existing worklist and independently recomputes the summary from the saved trial and candidate records.

## Reproduce the archived side

From the source checkout, run the archive check without a department host.

```sh
python3 -B experiments/rq-c/summarize_department_regeneration.py --archive-self-check
python3 -B -m unittest discover -s experiments/rq-c -p test_summarize_department_regeneration.py -v
```

The check reads all 7,200 rows in each of the three archived groups, verifies the pinned inputs, and reproduces the reported counts and intervals from the pinned P2 model analysis. Distinct candidate counts are checked independently against the recorded-label section of the pinned oracle audit. The test suite also uses simulated launcher records to exercise the complete reporting entry.

## Read an accepted department bundle

Use the retained regeneration phase directory and an independently reviewed SHA-256 of its `phase-result.json`. The phase receipt must record a complete regeneration, three launches, a covered qualification handoff and a clean before/after log comparison. The reporter verifies the file manifest, each launch's artifact bindings, and the retained alignment report against the actual runs.

```sh
python3 -B experiments/rq-c/summarize_department_regeneration.py \
  --regeneration-bundle "$P2_REGENERATION_DIR" \
  --phase-receipt-sha256 "$P2_REVIEWED_REGENERATION_SHA" \
  --out "$P2_NEW_STATISTICS_REPORT"
```

Verifier false-pass and false-fail use the last recorded execution of each judged skill as truth. The existing task-cluster bootstrap draws 10,000 resamples. Cell usability counts skills with at least half of recorded calls successful. The distinct-candidate count uses the first judged skill for each task and exact code. Alignment exposes the first divergent position and fields. Numerical summaries preserve separate before/after denominators.

This is the recorded-label portion of the comparison. The planned exploratory oracle re-tally has its own analysis, and department qualification and regeneration require their own reviewed approvals.

Each rate carries up to three intervals: `wilson95`, `taskBootstrap95` (percentile) and `taskBootstrapBca95`. A rate with a zero denominator has none, and the tool leaves out the BCa interval when it cannot compute one. Read the two task-clustered intervals, `taskBootstrap95` and `taskBootstrapBca95`; the manuscript reports the BCa one, beside the Wilson interval. `wilson95` treats skills as independent and is too narrow when one task supplies most of a numerator. The counts are in `confusion` (`tp`, `fp`, `fn`, `tn`), where a positive is a verifier pass and truth is the last recorded execution of the skill. The rate keys are: `hallucinationRate` = FP/(FP+TN), the false-pass rate; `missRate` = FN/(FN+TP), the false-reject rate (called false-fail above); `falseDiscoveryRate` = FP/(FP+TP); `falseOmissionRate` = FN/(FN+TN); `agreement` = (TP+TN)/(TP+FP+FN+TN).
