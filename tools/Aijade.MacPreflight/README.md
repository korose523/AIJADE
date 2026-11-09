# Bounded Mac model preflight

This development tool reuses the existing RQ-C prompt builders and format parser.
It does not run the P2 primary experiment, select models by accuracy, qualify a
device, or write to the historical run directories. See the dated plans under
`experiments/plans/2026-11-09-mac-*` and
`docs/MAC-MODEL-PREFLIGHT-2026-11-09.md` for scope, all attempts and limitations.

Use the repository's pinned .NET SDK and an existing isolated Python environment
with `psutil` (the recorded run used 7.2.2). No new Python packages are needed
for the exporter, call counter or result analysis beyond the monitor dependency.

1. Build `Aijade.MacPreflight.csproj` with the project SDK, then export a **new**
   fixture file with the executable's `<repository-root> <new-fixture.json>`
   arguments. This performs no model call, but checks the saved failed program
   in the existing sandbox to construct real retry feedback. Source, archive and
   DLL hashes are included in the fixture.
2. Start an owned private Ollama listener with one loaded model and one parallel
   request. Record its PID, version and complete model digests. Do not point the
   monitor at a production listener or terminate unrelated processes.
3. Run `run_preflight.py run --repo … --fixtures … --out … --server-pid …`.
   Sampling, model order, request deadlines and resource bounds are fixed by the
   dated plan. The initial run checks the frozen source hashes before inference.
   A censored request remains a failed/unfinished observation.
4. After unloading, `check_admission.py --out <new-admission.json>` records the
   amendment's fixed 60-second admission window. A repeat requires its own
   recorded scope and output directory; it never replaces a stopped attempt.
5. Run the executable's `classify <result.json> <new-classification.json>`
   command to reclassify saved verdict formats with `OllamaBackend.ReadVerdict`.
   It performs no inference and checks no verdict accuracy.
6. `count_calls.py --repo … --out <new-counts.json>` counts the full archived
   controls and their first-five-trial prefixes. `analyze_preflight.py` audits
   requests, replies, identities and source bindings, then calculates separate
   conditional time scenarios for each supplied `--phase` directory.

All model outputs and measured timings belong to the output folder, never to
the primary result tables. Available RAM/swap are system observations; summed
owned-process RSS includes shared mappings. A successful 4096 allocation is not
an arbitrary full-length context/output stress test. Keep the original attempts,
absolute swap levels and all amendments. Unload the owned models and stop only
the private service created for this work when finished.

Run the bounded monitor fault checks with `python -m unittest discover -s
tools/Aijade.MacPreflight -p test_preflight.py -v`. They test incomplete replies,
metric validity, resource-duration bounds, source drift and verdict-prefix
parsing; they do not constitute research validation.
