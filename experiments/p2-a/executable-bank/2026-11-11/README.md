# P2-A executable proposal and runtime measurements

This stage materializes the 422-task, 115,185-case candidate proposal from the earlier candidate-review archive and connects it to the normal RQ-C CLI. Author review remains pending. The reference execution and the mock control are engineering measurements; neither estimates a model verifier error rate. Plan eae8aca was committed before this implementation. The input lock fixes the export independently of gzip timestamps.

## Local reconstruction

Use Python 3.9 or newer and the repository-pinned .NET SDK. No model server is needed for these checks. The exporter reuses or reconstructs the pinned release and exact-variant packs and validates them against their published hashes. Use new writable output directories outside the repository. The materialized bank is approximately 195 MB; its full reference outputs remain in the earlier public archives.

```sh
python3 experiments/p2-a/executable-bank/2026-11-11/export_bank.py --work /tmp/p2a-work --out /tmp/p2a-bank
dotnet build tools/Aijade.Experiments -c Release
# Select the built DLL from the chosen artifacts directory.
dotnet Aijade.Experiments.dll p2-bank-check --bank /tmp/p2a-bank/manifest.json --task HumanEval/0
dotnet run --project tools/Aijade.Rqc -c Release -- --public-bank /tmp/p2a-bank/manifest.json --seed 42 --trials 1 --rounds 1 --tasks 12 --p-correct 1 --save-candidates --out /tmp/p2a-control
```

The `--public-bank` option pins the manifest, checks file hashes, and uses a balanced seeded permutation instead of the historical 44-task sample. The bank identity and allocation rule enter the run fingerprint. Every public-bank step and candidate carries this identity. Resume rejects a changed bank or design, and the public mock consumes and checks its recorded random draws before continuing. Existing runs without this option keep their original fingerprints and golden records.

## Measurement boundaries

`replay_bank.py --bank ... --executable ... --dll ... --out ... --final` runs every reference in a separate bounded process and records every planned case. It requires a clean checkout descended from the plan commit and an exact input-lock match. Limits are 15 CPU seconds, 30 wall seconds, 2 GiB sampled RSS and 64 MiB process output per task, with the Jint 2,000 ms / 512 MiB allocation settings. Unknown cases remain unknown. The full input-case map and reference identities are preserved separately from each new run.

Prompt lengths and SHA-256 values come from the actual generation and A/B verifier builders. Replacing all expected literals must leave all three prompts byte-identical. Measurements with a fixed `function solve() {}` candidate separate test-input overhead from reference-code length. UTF-8 bytes and UTF-16 units do not establish token counts or context fit. No prompt is sent to a model in this stage.

Balanced allocation gives floor(ST/N) or ceil(ST/N) exposures for every task per condition per round and distinct tasks inside each trial when S <= N. Counts include tasks with zero exposure. The model-study development/selection split, seed, N/T/q, precision target, device qualification and final author decisions remain future study inputs. The engineering seed 42 does not settle them.

The complete corrected replay at 6e6d0c8a023f0d20067b5eeb433d64d0823947c1 agrees on all 422 tasks and 115,185 retained cases. All 422 expected-output noninterference checks pass. The reference-backed normal CLI completes all 48 steps. Continuation from 32 recorded steps gives identical decision records, with execution durations retained separately. Changed-manifest, changed-design and public-to-legacy prefixes are all refused before the CLI creates its run output. No model is called.

Generation prompts span 556–1,597 UTF-8 bytes. Verifier A spans 24,547–185,030, and verifier B 24,279–152,715 with the reference candidate. Empty-candidate maxima are 160,898 and 128,583. These lengths are engineering capacity observations; token counts and model context fit remain unmeasured. Fix the model-specific tokenization, chat-template and any prompt-budget rule before a model pilot.

The allocation check includes N=258/q=8/T=172 and N=422/q=8/T=282 with twelve slots. The latter gives 414 tasks eight exposures and eight tasks nine exposures per condition per round. These are design examples; no development split or primary-study N/T/q is selected.

The first 188-task attempt is INVALIDATED_WHOLE_ATTEMPT. Its checkout-working-directory failures and the eight rows completed after a driver rebuild before termination are kept under results/rejected-replay/. None of its 90,331 recorded case rows enters the fresh complete replay. Earlier reference failures, exclusions and candidate decisions remain under candidate-review and javascript-port.

Run `python3 experiments/p2-a/executable-bank/2026-11-11/verify_archive.py` to check the complete outcome-to-source joins, input/reference identities, recorded process outputs, normal CLI continuation and identity refusals. Results are under results/replay/, results/engineering/ and results/summary.json. Source and release licences are kept in results/bank/. The executable 195 MB bank is locally reconstructed rather than duplicated in Git.
