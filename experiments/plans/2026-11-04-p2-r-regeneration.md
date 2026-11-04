# P2-R: Regenerating the second-host runs on a qualified device

*Authors: Zexiao Weng, MinPo Jung (corresponding). Not registered on an external platform: this plan is committed to the code repository on its own and sent to the supervisor as a PDF before its code is written.*
*Last revised: 4 November 2026. Code statements checked against commit `97aab7c` of the code repository.*
*Revisions: 27 October 2026 (added at the supervisor's request, review of 27 October, §4.3: this is the first task of December, because the main runs of P2-A and P2-B need the same device); 3 November 2026 (the archived scripts gain an output-directory argument; then, after the supervisor's review of 3 November: the host's error record as read in full, replacing the processor as a repair option and its record, what is done when the determinism check fails, and the conclusions of the skill study that the comparison checks); 4 November 2026 (the sandbox and the bench stay as they are for the comparison, and the re-tally of the recorded runs is repeated on the regenerated records; then, for a start in November as the review of 3 November, §7.3 and §8.2, allows: the device, the tools, the periods and the criteria of step 1 are fixed, the power settings changed during the fault investigation are returned, the determinism check uses the runner itself, and the conditions on the host during the runs are stated).*

## Study information

**Research question.** When the three runs generated on the second host are generated again, with the archived settings, on a device whose qualification has been established and recorded, do the model's replies, the execution verdicts and the summary statistics agree with the archived runs?

**Background.** Three runs of the skill study were generated on a Windows host, host 2 (RTX 5080, Intel Core i9-14900KF), whose CPU has logged hardware errors: the second-family control (llama3.1:8b) and the prompt-template controls A and B (qwen2.5-coder:7b-instruct). The runs were generated on 18 October 2026, according to their run logs. When the host's hardware-error log (Windows System log, provider `Microsoft-Windows-WHEA-Logger`) was read in full on 21 October 2026, it held 27 corrected machine-check events between 29 July and 21 October 2026 (20 internal parity errors, 6 translation-lookaside-buffer errors and 1 other) on five processor cores (microcode revision 0x133); the log is circular, so the counts are a lower bound, and the three runs fall within this period. In those runs the runner, the sandbox, the execution oracle and the analysis ran on the main host; the second host served only the model. The three summaries record no code commit (`gitHash` is "unknown"): the runs were made on 18 October from a working copy, before this repository's first commit (`3c24256`, 23:14 that day), and whether that copy matched the commit is not recorded. An integrity audit of the archived text (code repository `8b45434` → `c5dfe26` → `2502e0b`) found no damaged characters, empty code or unparsable code, but it cannot detect a change that leaves well-formed text.

**The host since those runs.** Its Ollama server has moved from 0.40.0 to 0.40.12 (read on 3 November 2026; the digests of the two models are unchanged), because the desktop application that serves it updates itself. Its operating-system power settings were changed on 20 and 21 October 2026 during the fault investigation (maximum processor state 99%, then 90%; minimum processor state 90%; processor idle disabled). It carries the daily work of the author's other projects.

**What a regeneration can and cannot show.** It does not decide whether the fault changed the archived runs: a second run cannot show that, and the comparison of the two hosts already mixes the host with a server version (Ollama 0.40.0 against 0.35.1). Its purpose is to obtain results generated on a qualified device. Greedy decoding can also differ between GPU models, drivers and builds, so a difference on another device is not evidence of a fault.

**Hypotheses.** None directional.

## Design plan

**Study type.** Re-generation of existing runs with fixed settings; no human participants.

**Timing.** Step 1 is not an analysis and may start once this plan has been sent (supervisor's review of 3 November 2026, §7.3). Steps 2 and 3 call the models, so steps 2 to 4 start on or after 2 December 2026, the start of the supervisor's schedule for new runs.

**Step 1: device qualification (device, tools, periods and criteria fixed now).** The device is host 2 with its processor replaced. Updating the firmware and microcode is not a repair here: the microcode (0x133) is already later than Intel's fix for the instability of its 13th- and 14th-generation desktop processors (0x12B), and the author could not enter the firmware setup on 21 October 2026.

1. *Export before the repair.* In Windows PowerShell, the System log's hardware-error events, and the oldest entry the log still retains, which answers the open question of how far back it reaches:
   - `Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Microsoft-Windows-WHEA-Logger'} | Sort-Object TimeCreated | Select-Object TimeCreated,Id,LevelDisplayName,Message | Export-Csv -Encoding UTF8 <file> -NoTypeInformation`
   - `Get-WinEvent -LogName System -Oldest -MaxEvents 1`
2. *Repair.* The processor is replaced. The operating-system power settings return to the power plan's values before 20 October 2026 (maximum processor state 100%, minimum 5%, processor idle enabled), so that the device is qualified in the state in which it runs. If the firmware setup can be entered at the replacement, the processor's power profile is set to Intel's default settings; either way, what could be read is recorded.
3. *Stress test, 24 hours.* Prime95 (version 30.19 build 20; torture test, Blend, all logical processors) and FurMark (version 2.11.0.4; its stress test at the display's resolution) run together. A later version of either is recorded as used.
4. *Observation, 7 days.* Normal use of the host, starting when the stress test ends. It may include the daily work of the author's other projects, and the record lists what ran.
5. *Criterion.* The device is qualified when, from the start of the stress test to the end of the observation period, the System log holds no event from `Microsoft-Windows-WHEA-Logger` and no unexpected shutdown (Kernel-Power event 41 or a bug-check record), and Prime95 reports no error in `results.txt`. Process crash dumps in that period are listed; one that cannot be explained is examined as a possible fault. If the criterion fails, the cause is examined and recorded, and the stress test and the observation period start again; every attempt is reported.

The stress test and the observation period are the practical criterion of qualification. Passing them is not evidence that the archived runs were unaffected, nor a guarantee that the device will not fail later.

The record lists the device (CPU, GPU, driver, operating system build, firmware version, microcode revision), what was changed and when (for the replaced processor, the part, its serial number where readable, and the date), the tools with their versions and settings, the hardware-error events in the retained System log (their count, the earliest and latest, and the earliest date the log still retains), and the stress-test output. Each export is archived with the command that made it and its SHA-256, beside a history of the host (dates, events, and the runs of the author's projects made on it), to which the documents of those projects refer. The history and the raw exports are kept in the authors' private papers repository; `experiments/rq-c/device-qualification.json` carries the counts and the SHA-256.

**Step 2: determinism check with the runs' own requests.** The earlier pre-check (`tools/Aijade.Substrate verify`) sends one short probe under its own profile (temperature 0, top-k 1, a 32,768-token context, 2,048 output tokens), while the runner's requests set only the temperature, the seed, `num_ctx` and `num_predict`. It therefore bears on greedy decoding on that server, not on the identity of the runner's requests (skill paper, Supplementary S1). On the qualified device the check uses the runner itself. For each of the three runs, the runner's command of step 3 is run with `--trials 5` (1,200 steps, 32 of the 44 tasks, about 250 generations and 130 verifier replies) and an output directory of its own, five times. Before each pass the model is unloaded (`keep_alive` 0), so that a pass starts as a run does: the model loads, the warm-up request is discarded, and the steps follow in the run's order, with context 4,096 tokens, replies capped at 4,096 tokens, temperature 0 and the runs' sampling seed (3759066737, derived from seed 42). At the archived rate this takes about 35 minutes of GPU time. Pass: for every step, the generated reply, the extracted code, the verifier reply, the verdict and the execution result are identical across the five passes of each run. As a positive control, `tools/Aijade.Substrate verify --model <tag> --seed-strategy fixed --control` is run for each model; its opened sampling (temperature 1, top-k 40, top-p 0.95) must give divergent outputs. The passes are not compared with the archived runs; that is step 4.

If the check fails, the device is not judged unqualified on the outputs alone. The cause is investigated first, to separate a device fault (new hardware-error events, crashes, or a failure that follows the device) from nondeterminism of the runtime (a failure that also appears on the main host with the same server version and settings). If the device stays qualified, whether step 3 becomes repeated regenerations that record how the outputs vary is decided with the supervisor and recorded as a change of this plan before step 3 starts.

**Step 3: regeneration.** The three runs are generated again with the archived settings and the same scripts (`experiments/rq-c/run-family-gpu.sh llama3.1:8b`, `run-template.sh A`, `run-template.sh B`): trials 30, rounds 5, tasks 12, seed 42, temperature 0, warm-up request, `--timeout-ms 3600000`, `--max-reply-tokens 4096`, `--num-ctx 4096`, verifier template A or B. Since the first commit of the repository (`3c24256`), the runner, its prompts, the tasks, the sandbox and the skill registry have changed only to record the code commit (`ca0d860`), to expose helpers to an analysis (`761165d`) and in comments (`b75bea8`); the runs are made from a clean checkout of the commit of this plan's code, with no earlier build products and with `AIJADE_GIT_COMMIT` set. Because the archived runs record no commit, no record excludes a difference between the working copy they were made from and `3c24256`. Output goes to `experiments/rq-c/regen/<run>/`; the archived runs are not touched. As archived, the scripts write into the archived run directories, append to the archived logs (`run-family-gpu.log`, `run-template.log`, kept for the integrity audit) and stop at once when they find a finished run there; so they gain one argument, the output directory, used for the runs and the log alike, and nothing else in them changes.

**Conditions on the host during steps 2 and 3.**
- *Server.* Ollama 0.40.0, the version of the archived runs, from the official standalone Windows package (`ollama-windows-amd64.zip`, checked against the release's `sha256sum.txt`), with the desktop application closed and kept from starting. A difference the device forces is recorded as a deviation.
- *Models.* The digests of the archive (llama3.1:8b `46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e`; qwen2.5-coder:7b-instruct `dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364`), checked before the first step.
- *No changes.* No update of the server, the models, the GPU driver or the operating system between the start of step 2 and the end of step 3.
- *No other load.* The other GPU services and computations of the author's projects on this host are stopped.
- *Record.* At the start and the end of each run: the processes on the host, the server version and its `OLLAMA_*` environment variables, the model digests and the driver version.
- *Main host.* As in the archived runs, the runner, the sandbox and the oracle run on the main host, which reaches the server over Tailscale. Its runtime version is recorded.

After step 3 the hardware-error export of step 1 is repeated. An event between the end of the observation period and the end of step 3 is reported, the device loses its qualification, and the runs made after the event are generated again once it is qualified again.

**Step 4: comparison.** The sandbox and the bench stay as they are, although the re-tally of the recorded runs (`experiments/rq-c/oracle_audit.py`, 4 November 2026) found a calling-rule gap and one debatable test case, so that the regenerated runs compare with the archived ones; the same re-tally is repeated on the regenerated records and reported beside them. Timings differ, so files are not compared byte for byte. Records are aligned by step and skill identifier, separately for each of the four conditions of each run. For every aligned step the comparison records whether the generated reply, the extracted code, the verifier reply, the verdict and the execution result are identical. Within a condition, later steps depend on earlier replies, so the comparison reports the first divergent step and the number of identical steps before it; after a divergence the condition is compared through its summary statistics only. The summary statistics compared are the false-pass and false-fail rates with their task-bootstrap intervals, usability by cell, and the counts of skills and distinct candidates.

## Sampling plan

**Existing data.** The archived runs, pinned by SHA-256:

| Run | `trials.jsonl` | `candidates.jsonl` |
|---|---|---|
| Second family, llama3.1:8b (`experiments/rq-c/family-gpu/rq-c-s42-ollama-t30-r5/`) | `56e40a5e54d6a3bbe2884d25bf5e6049d2dd4ecb5c338a177764d709766b4121` | `9f53d82b6e38ff5286fc62c062cc54579d7a6e8fa9a1b1232f84bea486ce4d61` |
| Template A, qwen2.5-coder 7B (`experiments/rq-c/template-gpu/A/rq-c-s42-ollama-t30-r5/`) | `73dfd090ff3410f1a24e62ff75ab69b0bab90a01fbedfe502ad285f7b6b18436` | `928a99838f7b57696c2e7fe4731bc3b2890b16c2ed7ef9461d1ad3dae61d2ae3` |
| Template B, qwen2.5-coder 7B (`experiments/rq-c/template-gpu/B/rq-c-s42-ollama-t30-r5/`) | `fc76a3cc69ed351108052c68772902a03b936aa728c28542a0de3ad74c7b07c0` | `fd4b5408eb2592a9322728e23b51ad669f82bbdcdc8d7b5365636a3ef9439be2` |

**Sample size.** Each run has 7,200 steps; each is regenerated once. No stopping rule beyond the runner's own resumption after an interruption, which is recorded.

## Variables

**Measured.** Per run and condition: identical steps before the first divergence, the first divergent step and what differed there; per run: the summary statistics listed in Step 4, archived and regenerated side by side; the device-qualification record and the determinism check.

## Analysis plan

**Reading (fixed in advance).**

| Outcome | Treatment |
|---|---|
| Every aligned step of all three runs has identical replies | The archived results stand. The dissertation (Appendix C, Section 5.6.8) and the skill paper state that a regeneration on a qualified device gave the same replies; this does not show that the fault had no effect before |
| Any reply differs | The regenerated runs become the main results for these three controls. The differences from the archive are listed (first divergence per condition and the summary statistics side by side), together with the changed environment and, for each conclusion of the skill study that rests on these runs, whether it changes: the second family's errors toward acceptance and the sign of its `missRate − hallucinationRate` under task resampling; the verifier passing every skill it judges under template B; the false-pass estimate of the main model with template A on the second host and its interval (Table 3.3, L3), and its comparison with the main run; and the second family's malformed verdicts scored as FAIL. A difference is not described as an effect of the fault, and no difference is attributed to the device alone, because the processor, the server package and the code may all differ from the archived runs |
| No device is qualified by 20 December 2026 | Alternatives are agreed with the supervisor that day: another GPU device (the same stress test and observation period, where the device allows), a paid API at an agreed cost, or narrower claims about these three controls |

The main 7B run (host 1, Ollama 0.35.1) is not regenerated and stays the reference for the false-pass rate of 59/139.

**Data exclusion and missing data.** None. A regenerated run that cannot finish is reported with the steps it reached.

## Other

**Plan and record.** This plan is pushed to the code repository on its own and sent to the supervisor as a PDF before its code (the scripts' output-directory argument and the comparison script used in steps 2 and 4) is written. Results record the plan commit and the code commit; deviations are listed with date and reason.

**Resources.** About 44 minutes of GPU time for the three runs on the original host (984, 807 and 849 seconds) and about 35 minutes for the determinism check, plus the stress test and the observation period. No paid service. Each download needs the author's permission: Prime95 (8.4 MB), FurMark (38 MB) and the Ollama package (about 1.47 GB). The two models are already on the host.

**Outputs.** `experiments/rq-c/regen/` (the three runs and the passes of the determinism check), `experiments/rq-c/regen-comparison.json` (alignment, first divergences, summary statistics side by side, input hashes, plan and code commits) and `experiments/rq-c/device-qualification.json` (the record of Step 1 and the determinism check of Step 2).
