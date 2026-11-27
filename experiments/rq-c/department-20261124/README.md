# P2-R on the department server, 24 November 2026: status, decision and read-only checks

Written 25 November 2026 (`bbf60bd`). Revised 26 November 2026 after a second read-only check. The revision corrects the
unit of the verifier counts and several statements of the first version, completes the list of deviations and adds the
addendum at the end. Neither check started a model or executed a candidate program. Times are Asia/Seoul (KST).
Revised again on 27 November 2026: the next section records the supervisor's decision of that day, the body text calls
the computer the department server except in the dated addendum of 26 November, which keeps its wording, and weaknesses
that the review names are added to deviations 3 and 4.

The prospective record is [`DEPARTMENT-EARLY-START-20261124.md`](../DEPARTMENT-EARLY-START-20261124.md) (589bc0f).
Group A used Ollama 0.40.0, group B (exploratory) 0.40.16. The groups are reported separately and never pooled. The
runs were made on the department server, a shared department computer running Windows. No number of either group
enters Chapter 5 or the P2 manuscript before the three steps of the decision below are done, and no number of group B
enters the P2 manuscript at any time.

The on-site records cited below (the log-anchor record `0eb1787`, the retry record `1b945b0`) and the records of the two
checks are in the private papers repository. The check records were drafted by Claude and await the author's sign-off;
the supervisor's review of 27 November 2026 asks the first author to sign them and the two on-site records, to send
them again by 30 November 2026 and to state separately, as far as known, when the warm-up was actually approved. This
revision follows the record of the second check, which prevails over the older records.

## Decision of 27 November 2026

The supervisor's review of 27 November 2026 decided how these runs are used.

- **The computer.** The computer used on 24 November 2026 is the department server of the approved plan.
- **Dates.** The supervisor does not hold the early start against the runs, because the review of 21 November 2026
  had let the experiments go ahead. The early start stays a fact in the list of deviations (item 1).
- **Group A** (Ollama 0.40.0, the archived service version) will be used as the P2-R group-A result after the three
  steps that the review lists in its section 1, point 1:
  1. The three source commits made on site (`9f67b1b`, `204af3a`, `fddf9a1`), the two approval receipts and the
     private directory of the second attempts, and the Ollama service logs are retrieved from the department server and
     checked as section 8 of the second check record lists; the three commits are then published. The review sets
     30 November 2026 for the retrieval.
  2. The exploratory re-scoring of the plan (see "Not done") is applied to groups A and B under a prospective record
     that the first author confirms and pushes before it runs. Its results are kept apart from the error rates computed
     from the recorded verdicts.
  3. The nine deviations listed in the first author's report of 26 November 2026 to the supervisor and the weaknesses
     named in the review are written into Section 5.10.3 and Appendix B of the dissertation. As of 27 November 2026
     this revision is in progress.

  Until all three steps are done, no number of group A or group B enters Chapter 5 or the P2 manuscript.
- **Grounds for using group A.** The first attempt of A failed on a criterion that the approved plan does not contain
  (five fixed-seed requests of the Llama control had to return the same output, a criterion the tool added; for this
  positive control the plan asks only that the open-sampling arm diverge) and on one GPU error event inside its
  observation window. The second attempt had no new error event inside its recorded windows and passed, and its
  qualification outputs equal those of the first attempt in all 15 starts, so the changes made after the failure did
  not change what the runner generated. The weaknesses that remain are to be stated in full; they are listed under
  "The four attempts" and "Deviations" below.
- **P2-R is not rerun.**
- **Group B** (Ollama 0.40.16) stays an exploratory record. Later it is reported only as one exploratory cell: never
  pooled or added with group A, never in a conclusion sentence, and not in P2. Next to that cell it is stated that the
  21 false rejections of its second-family run come from the later replies to one program (math-fib), not from 21
  independent errors.
- **The next run on the department server** (P2-A and later). Its control standard is fixed, sent to the supervisor and
  pushed before the run:
  - no warm-up that discards the first reply; instead, after each unload and reload of the model the same request
    sequence is repeated five times, and the replies at the same position, the first call included, are checked for
    identity; open sampling must diverge;
  - a first call that differs from the later ones is not a defect of the device but part of what is measured, so the
    main run records every verifier call and reports first and later calls separately;
  - whether a failed qualification stops the run or switches to repeated regeneration with the variation measured is
    written down before the run;
  - the usage time is agreed with the department member in charge, no other task uses the GPU during the run, and the
    run takes place on a day when the exclusivity check can pass.

## The four attempts

- **First attempts** (archives 291ef69c…, 45d81cc8…): `INCOMPLETE_DEPARTMENT_EVIDENCE`, no regeneration. The launcher
  stopped both with the error `open sampling control failed`, for different reasons. In A the control finished with the
  verdict `non-deterministic`: its fixed-seed arm gave two different outputs in five requests, the first differing from
  the other four, and its open-sampling arm diverged as required. The plan asks of this control only that the
  open-sampling arm diverge; the launcher and the audit also require the fixed-seed arm to repeat. In B the first
  generation request of the control failed with a connection error within one second of the second GPU error event, and
  the control wrote no result. GPU error events fell inside both windows (one in A, two in B); under stopping rule 1
  such an event is by itself a failed qualification. In B one of the fifteen starts (template-b pass 5) also differed
  from the other four template-b starts in 10 of 1,200 steps, so the repeated starts did not match either. Two of the
  fifteen model-unload logs of A and three of the fifteen of B list a third model, not part of the study, as resident on
  the same server.
- **Second attempts** (archives 6f7d000c…, 4b85864b…): `QUALIFICATION_EVIDENCE_COMPLETE`,
  `REGENERATION_EVIDENCE_COMPLETE`. On the Mac, `--audit-bundle` gives `CAPTURED_REPEATS_MATCH` for both, every file
  bound by the four phase receipts matches, and the files in `analysis/` were reproduced from the archives. These
  statuses mean that the evidence is complete. They are not an accepted qualification: both audits record
  `formalQualificationDetermined` as false and the runs carry the deviations below. The supervisor's decision on their
  use is the section above.
  The log captures of these attempts, which begin at 13:35 (A) and 15:52 (B), hold no GPU error event and no WHEA
  record.

## Files

`analysis/` holds the two-layer reports (12), first divergences (9) and the summaries of A and B. `A-archive` and
`B-archive` compare with the archived runs, `B-local` with the host-2 run of 19 November, `host2-version` the archive
with that run.

Added on 26 November 2026: `analysis/first-occurrence-A.json` and `analysis/first-occurrence-B.json`, the outputs of
[`../first_occurrence_report.py`](../first_occurrence_report.py) for A and for B. They count, for each group separately,
how often the reply to the first occurrence of a request differs from the replies to its later occurrences (see the
addendum). The tool reads retained run records only: it calls no model and executes no recorded program. Its output for
the public runs is [`../first-occurrence-archive.json`](../first-occurrence-archive.json).

## Reading

- On programs that occur in both runs the execution oracle never conflicts. The comparisons overlap, so their counts are
  not independent samples.
- The verifier's verdict can differ on an identical program, between runs and inside one run. In the two
  self-verification cells the runner calls the verifier once for each new skill, and a reused skill keeps its verdict.
  One usable math-fib program (SHA-256 db5d25bc…) was verified 22 times in every second-family run: 1 pass and 21 fails
  in group B, 21 passes and 1 fail in the archive and in group A, and 22 passes in the host-2 run of 19 November. By
  execution record the counts are 5 and 21, 105 and 1, 105 and 1, 110 and 0, because every passed skill of this program
  is reused in the four later rounds. The first version of this file gave 5 and 105 as numbers of passing verdicts; they
  are execution records. In the archive, in A and in B the odd verdict is the first of the 22 calls. All 21 false
  rejections of B's second-family run concern this one program, and the task-bootstrap interval of the false-omission
  rate of that run is [0, 1], so no difference from the archive is established. Group A also differs from the archive on
  identical programs: an unusable parse-query-string program passes in 9 of 9 calls in the archive and fails in 18 of 18
  in A (template A), and the verdict of one call on a parse-csv-line program differs (second family). See the addendum.
- Inside one run the verifier's reply to the first occurrence of a request can differ from its replies to later
  occurrences of the same request. The archived runs show this too. The cause inside the model service is not
  established.
- The Wilson intervals in the summaries treat skills as independent; the task-clustered intervals are the ones to read.

## Deviations

1. **Dates.** Group A ran eight days before its approved start of 2 December 2026. Group B ran before the supervisor had
   decided on it. The prospective record states both.
2. **Log anchor and collector.**
   - The oldest retained log record names another computer, and the collector at `589bc0f` refuses such a record by
     design (stopping rule 3). The author chose the pinned-anchor patch of host 2 (on site: commit `9f67b1b`). The
     record of this choice was pushed at 10:59:55, before the first attempt began (11:03). Rule 3 orders a pushed
     follow-up record first and the decision on the patch after it. The record reports the patch as already committed
     locally, so the decision and the patch came before the push; the patch was used in a run only after it.
   - The note shipped with that patch
     ([`windows-retention-fix.patch`](../host2-local-20261119/delivered/windows-retention-fix.patch)) requires an
     independent configuration review before use in a departmental phase. No retained record shows such a review on 24
     November; the author has still to confirm this point.
   - A second edit of the collector came after that push and before the first attempt (`204af3a`; the script that made
     it was saved at 11:02). With it the collector prefers a copy of its helper script on the Windows system drive. No
     record preceded this edit. Both first attempts name `204af3a` as their source commit, and the commit of the second
     attempts (`fddf9a1`) is built on it. Neither edit touches the code that classifies events.
   - What can be checked from this repository: the change below, applied to
     [`collect_department_windows.py`](../host2-local-20261119/delivered/source-delta/experiments/rq-c/collect_department_windows.py)
     of the host-2 release, gives a file with SHA-256 92bcd89b…, the collector hash in every log capture of the four
     attempts; `collect_department_windows.ps1` at `589bc0f` has SHA-256 78e40388…, the helper hash in the same
     captures.

     ```
     - HELPER = Path(__file__).with_suffix(".ps1").resolve()
     + LOCAL_HELPER = Path("/mnt/c/aijade-p2r/collector/collect_department_windows.ps1")
     + HELPER = LOCAL_HELPER if LOCAL_HELPER.is_file() else Path(__file__).with_suffix(".ps1").resolve()
     ```
3. **The control.** A discarded warm-up request was added to the control after its failure (`fddf9a1`). It repeats the
   measured prompt, so it discards the request that differed in A's first attempt, and its output is not recorded. The
   change is in the control tool; the runner is one file in all four attempts (item 6). The qualification outputs of the
   two attempts are identical in A (15 of 15 starts) and in 14 of 15 starts in B. The other start is template-b pass 5
   of B's first attempt. Its first 200 steps took 480 s against about 36 s in the other four template-b starts. Two of
   its generation requests returned the output of their first occurrence a second time, which accounts for its 10
   differing steps; both were answered at least seven minutes before the first of the two GPU error events of that
   window (see the addendum). The plan says that when determinism cannot be reproduced the supervisor decides, before
   the main run, whether to switch to repeated regeneration with the variation measured; the supervisor was not asked
   before the second attempts.
4. **Retry preconditions.** The retry record required a passing exclusivity check, a paused co-tenant (the other project
   on the computer) whose status check returned `CLEAR`, and a model service on a separate port (11500). There is no
   passing receipt and no retained co-tenant status, and the service ran on the default port 11434. According to the
   on-site notes, the other project was using the same GPU during the first attempts. The only retained receipt of the
   exclusivity check is a FAIL at 13:51. The check looks back 24 hours, and two WHEA 17 records (10:10 and 10:27) and
   three GPU error events (11:33, 13:29 and 13:30) made a pass impossible that day. Both WHEA records precede the first
   attempts and lie outside every observation window; the second, 18 seconds after the boot, names an NVIDIA device. All
   four attempts ran in one boot session, and group A's second attempt began about 35 minutes after the last GPU error
   event. The retry record was pushed at 14:04:35, about one minute before group A's second qualification began, and it
   is marked a draft. It gives 14:05 for the author's approval of the warm-up and 14:10 for a probe, but its text was
   saved at 14:04:18 and already reports the probe, so 14:10 is not the real time of the probe. The real time of the
   approval, and whether it preceded the source change saved at 14:02:41, cannot be established from the retained files.
5. **Operator confirmation.** The deployment kit (the scripts taken to the department server) asks the operator to
   retype the SHA-256 of the qualification receipt before regeneration starts. A wrapper typed it for B, and a
   continuation script skipped the step for A. The launcher's own checks of the qualification receipt ran in both
   groups.
6. **Source and evidence.** Source commits `9f67b1b` (pinned anchor), `204af3a` (local helper path) and `fddf9a1`
   (warm-up) and the approval receipts of the second attempts are still on the department server. **The full source of
   the run is therefore not public yet.** The commits are to be retrieved, checked and then published. The private
   archive made after the first attempts holds build output and the evidence of those attempts, and no source. The
   runner DLL is one file in all four attempts (SHA-256 a0048ccf…), modified at 10:35 on 24 November, before the three
   on-site commits were made. The commit ids in the receipts and summaries (`204af3a`, `fddf9a1`) come from the approval
   receipt, which the launcher hands to the runner; they do not show which commit the file was built from. Not retained
   at all: the output of the kit's host check, a start record of the model service that served group A's first attempt,
   and the console output of group A's second attempt.
7. **Environment.** Windows 10 and Ubuntu 26.04 with NAT networking, and a display driver updated that morning. The kit
   was prepared for Ubuntu 24.04, and its setup script was adapted on site (a fixed kit path and an ICU package chosen
   for the release); neither on-site record pushed before the runs names the Ubuntu version. Windows 10 has no mirrored
   networking, for which the kit provides a NAT path, and the log-anchor record `0eb1787` noted this before the runs.
   According to the on-site notes, a firewall rule was added, two existing block rules were
   disabled and the PowerShell execution policy was changed for the run, and all were restored at the end. Only the
   notes show that they were restored.
8. **Analyses.** The two-layer reports, first divergences and summaries were first computed on the department server
   on 24 November, in part while group B's second attempt was running. The prospective record placed the analyses later,
   on the Mac. The scripts read result files and call no model. The Mac checks recomputed the files from the archives
   with the same result.
9. **Model service.** The model service of the second attempts kept a loaded model for 24 hours, that of the first
   attempts for 5 minutes (model-unload logs). The retry record also states three further measures: a limit of one
   loaded model, for which no start record of the service is retained; the removal of the third model from the research
   model store; and the stopping of the other project on the computer. No check output is retained for the last two. The
   third model of the first attempts (`qwen2.5-coder:1.5b`, see above) is in none of the model-unload logs of the second
   attempts (eighteen in each group). How each service was started is still to be established from the service logs,
   which are on the department server.

## Not done

As of 27 November 2026 the exploratory re-scoring of the plan has not been applied to A or to B, and no re-scored number
exists. It is not a read-only analysis: the historical rule replays every distinct recorded program in Node under three
label sets, so it executes candidate programs and needs its own execution approval
([`DEPARTMENT-EXPLORATORY-ORACLE.md`](../DEPARTMENT-EXPLORATORY-ORACLE.md)). The replay launcher also checks the
approval receipts of the second attempts, which are still on the department server. It runs under step 2 of the
decision above. The prospective record of 23 November calls this re-scoring the exploratory re-tally and lists it among
the read-only analyses on the Mac; this paragraph replaces that wording. The retrieval of step 1 of the decision has not
been done either.

## What the run exposed about the tooling

The kit of 24 November and the frozen tools are kept as they ran. Repairs are proposals for a next revision, because the
three on-site commits are not in the repository yet. A review of 26 November found (place of each repair in brackets):

- Display and reporting (next kit, repository): the launch script showed nested statuses and not the audit status; the
  launcher's summary and stop reason hide what failed; the reports state neither their unit nor their inputs.
- Controls that can be bypassed or skipped (next kit, plan text): the confirmation is read from standard input; the
  receipts of the exclusivity check, the service start and the co-tenant pause are optional.
- Evidence not captured (next kit, repository): approvals, on-site commits, the build commit, both arms of the control.
- Preconditions and gates (plan text first, with the supervisor's agreement): the anchor rule refuses both Windows hosts
  used so far, the 24-hour rule could not be met that day, and the control is stricter than the plan. The decision of
  27 November sets the control standard of the next run (see above).

## Raw archives

Raw archives stay private because their log captures name the host and hold event XML.

## Addendum, 26 November 2026: where the verifier's verdict changes

Analysis of 25 and 26 November 2026, read from the retained `trials.jsonl` and `candidates.jsonl` of the archive, A, B and the host-2 run of 19 November. No model was called and no candidate program was executed. A and B are listed separately; B is exploratory. The counts under "Scope inside a run", "Scope across runs" and "Rates" and the verdict sequences come from [`../first_occurrence_report.py`](../first_occurrence_report.py); its outputs are `analysis/first-occurrence-A.json` and `analysis/first-occurrence-B.json` here and [`../first-occurrence-archive.json`](../first-occurrence-archive.json) for the public runs. The other counts (qualification starts, execution records, the comparison of the template-A and template-B runs) come from the read-only checks of 25 and 26 November.

**Unit.** In the two self-verification cells the runner calls the verifier once for each new skill; a reused skill keeps its verdict. The math-fib program (SHA-256 db5d25bc…) was verified 22 times in every second-family run (11 trials, two self-verification cells, round 0): archive 21 passes and 1 fail, A 21 and 1, B 1 and 21, host 2 local 22 and 0. The counts 105, 5 and 110 are execution records.

**Input.** The request text is not stored. Rebuilt from the runner's source, the task bank and the recorded task and code, the 22 requests are the same inside a run and across the four runs (same model digest, template A, temperature 0, seed 3759066737, 4,096-token context and reply limit, one user message). For the archive no source commit is recorded; the first commit of the repository, made on the evening of the archived runs (18 October 2026), builds the same request. For A and B the on-site source commits of the run (the last, `fddf9a1`, is the commit named in the approval receipts of the second attempts) are not public yet; the runner DLL was built before them (Deviations, item 6). The recorded runner hash (a0048ccf…) is the same in both groups and both attempts, but it covers the entry assembly only and not the library that builds the prompt. The build tree of the first attempts is in the private archive: its library holds the public task bank byte for byte and every prompt line of the public source. The approval receipts that list the build of the second attempts are still on the department computer. A's qualification outputs are identical in the two attempts (15 of 15 starts), and the first five trials of each regeneration equal its first qualification start step by step.

**Position.** The 22 calls are at the same steps in every run. Each follows the generation request of its own step, which returned the same program every time.

| Run | Call 1 (step 3608) | Calls 2 to 22 |
|---|---|---|
| Archive (host 2, 0.40.0) | FAIL | PASS, one text |
| A (department, 0.40.0) | FAIL, the archive's text | PASS, a shorter text |
| B (department, 0.40.16) | PASS, the archive's PASS text | FAIL, the archive's FAIL text |
| Host 2 local (0.40.16) | PASS | PASS, the same text |

The FAIL text objects to the running time of the recursion, not to its results.

**Scope inside a run.** Verifier requests sent more than once whose first reply differs from the later replies (second family / template A / template B): archive 13 of 51, 0 of 55, 4 of 49; A 13 of 51, 1 of 55, 6 of 50; B 15 of 51, 1 of 54, 6 of 51; host 2 local 10 of 50, 2 of 57, 6 of 50. From its second occurrence on, the reply to a verifier request did not change between two occurrences unless another verifier request for the same task with different code was sent in between (each of the 12 runs has 581 to 607 pairs of consecutive occurrences with no such request in between, and in none of them did the reply change). Every later change followed such a request: one in the archive (template A), two in A (second family, template A), five in B (second family, template A, three under template B) and none on host 2 local. The verdict changes, always between the first call and the later ones, for these requests, listed by run: archive second family (math-fib, one parse-csv-line program), A second family (math-fib), B second family (math-fib, one str-rot13 program), host 2 local template A (one arr-flatten program). Generation requests show the same structure.

**Scope across runs.** Paired calls (same step, same task, same code) whose verdict differs, for second family, template A and template B: A against the archive 1 of 603, 9 of 762, 0 of 694; B against the archive 22 of 562, 0 of 756, 0 of 688; B against host 2 local 38 of 655, 0 of 796, 0 of 724; host 2 local against the archive 1 of 563, 0 of 792, 0 of 716. Programs: math-fib db5d25bc; parse-csv-line 2b0f633e (A's reply does not begin with PASS or FAIL and is read as FAIL); parse-query-string 51effba9 (unusable; archive PASS in 9 of 9 calls, A FAIL in 18 of 18, so A is right where the archive is wrong); str-rot13 b8286b4f (unusable; host 2 local PASS in 18 of 18, B PASS once and FAIL 17 times).

**Qualification.** Every fresh start repeats the pattern: A gives FAIL then PASS in 10 of 10 starts, B gives PASS then FAIL in 10 of 10. In the control of A's first attempt the first of five identical greedy requests differed from the other four. That control sends its own request (32,768-token context, 2,048-token reply limit, seed 42), and its first request is also the first after the model was loaded with that context, so it does not separate a first occurrence from a first request after a load. The warm-up added afterwards repeats the measured prompt and discards that first request. `CAPTURED_REPEATS_MATCH` means that the same request sequence gave the same outputs. It does not mean that a reply depends on its request alone.

**Where the state may be kept.** The first-against-later differences suggest that earlier requests leave state behind. Three observations fit the hypothesis that this state is held on the serving side for as long as the model is loaded; none of them tests it. (1) The archived template-B run was started about half a minute after the archived template-A run ended, without unloading the model. Its first output for each of the 44 task prompts equals the later output of the template-A run, and none of its generation prompts shows a first-against-later difference. In the two cells without self-verification, where both runs send the same requests, 10 of 3,600 steps differ. (2) In A, in B and on host 2 local the launcher unloaded the model before each run; there the same 3,600 steps are identical between the template-A and template-B runs. (3) In the one qualification start that differs (B, first attempt, template B, pass 5) two generation requests returned the output of their first occurrence a second time; if the state was lost once between the requests of steps 124 and 128, that would account for exactly these two; a single loss at any other position would not.

**Rates.** The skill-level rates count every call. A program that is created n times enters once with the reply to its first call and n − 1 times with the reply to its later calls. Relabelling every skill with the first-call verdict of its program, or with the later-call verdict, and leaving the realised skills unchanged, gives these second-family false-reject counts: archive 1 observed, 22 or 0; A 1 observed, 22 or 0; B 21 observed, 0 or 22.

**Reading.** With temperature 0 and a fixed seed the verdict is not a function of the program alone. In each of the twelve runs examined here (Ollama 0.40.0 and 0.40.16) the reply to the first occurrence of a request could differ from the reply to its second occurrence, and every later change followed another request for the same task. The second rule does not hold for the main run under Ollama 0.35.1: there later replies also changed without such a request (18 of 590 verifier pairs and 6 of 1,226 generation pairs, `../first-occurrence-archive.json`). For the math-fib program the replies also differ between the two service versions on the department computer (A and B, each pattern in 10 of 10 starts) and between the two computers under 0.40.16 (B and host 2 local, 10 of 10 and 5 of 5 starts). The B result cannot be assigned to the version alone or to the computer alone: host 2 local (0.40.16) does not show it, and A (same computer) fails the program once, at the first call. For this program the reply to the first call is the same on both computers under each version (the FAIL text under 0.40.0, the PASS text under 0.40.16); the later reply is FAIL in B only. The records fit the hypothesis that state from earlier requests is held on the serving side for as long as the model is loaded; whether such state exists, and how it would be kept and used, is not established: the records hold no request timing or token counts, and the service logs of the department runs are still on the department computer.
