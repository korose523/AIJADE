# P2-R on the department computer: early group A and exploratory group B

Prospective record, written on 23 November 2026 (Asia/Seoul) before any department run. The author decided; Claude drafted. The Chinese copy is in the private papers repository, `追加实验注册稿/P2-R_系服务器提前执行与B组记录_20261123.md`.

**Outcome (added 26 November 2026).** The runs took place on 24 November 2026. They did not follow this record in every respect: three code changes were made on site (a pinned log anchor and a local helper path in the collector, and a discarded warm-up request in the open-sampling control), the analyses were first computed on the department computer, and the preconditions that a later retry record set for the second attempts were not all met. The list under "Out of scope" places the exploratory re-tally among the analyses that run read-only on the Mac; the re-tally needs the Node replay named in the same list, which executes the recorded programs under its own approval. The outcome and the full list of deviations are in [`department-20261124/README.md`](department-20261124/README.md). The text below is unchanged.

## Basis

- **Supervisor's review of 21 November 2026.**
  - Approves the department plan: group A (Ollama 0.40.0) from 2 December 2026.
  - Whether to add group B (0.40.16) is decided at the December meeting.
  - States that experiments may go ahead without waiting for a reply. Only P2's main results must come from the department server.
- **Supervisor's review of 23 November 2026.** Repeats "P2-R (A) on the department server from 2 December".
- **The author's decision of 23 November 2026.**
  - Run on 24 November on the department Windows computer allocated to the author: an NVIDIA GPU, with administrator rights.
  - Run both groups.

## Deviation 1: group A starts early

The start date moves from 2 December to 24 November 2026. Everything else follows the approved plan and the existing launcher, and no research code changes:

- **Worklist:** the SHA-256 is `04bf4f7f96b41b888ce22f81de4bf533b3d3edc53d38a0f3f6828785b898b91d`.
- **Launcher:** `launch_department_regeneration.py`. The source commit is the one that adds this file.
- **Qualification:**
  - five fresh launches per group, each after a verified model unload;
  - two open-sampling controls;
  - Windows System and Application event logs captured before and after by `collect_department_windows.py`.
- **Regeneration:** three complete regenerations, each of 7,200 steps.
- **Models:**
  - `qwen2.5-coder:7b-instruct` with digest `dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364`;
  - `llama3.1:8b` with digest `46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e`.
  - Both are copied from the author's drive with the original manifests. Every blob is checked by SHA-256 when copied, and the launcher checks the digests again through `/api/tags`.
- **Approval receipt:** it binds the supervisor's review of 21 November and the plan the supervisor approved (`P2-R_系服务器方案_20261120.pdf`). Its allowed window is the window below.

If qualification and the log audit pass, group A is reported as the department group A, with this date deviation stated, for the supervisor to accept or not.

## Deviation 2: group B before the supervisor's decision

- **What runs:** after group A, on the same computer, Ollama is replaced by 0.40.16. Group B then runs the same qualification and the three regenerations. It has its own approval receipt and its own output directories.
- **How it is used:** it is exploratory and is reported separately, as the "department × 0.40.16" cell of the 2×2 comparison in the approved plan. It is not pooled with group A and does not enter Chapter 5 or P2 unless the supervisor decides to add group B.

## Window and order

- **Window:** 2026-11-24 08:00 to 2026-11-26 00:00 (Asia/Seoul). No phase starts outside it.
- **Order:**
  1. Group A: Ollama 0.40.0, qualification, regeneration.
  2. Group B: Ollama 0.40.16, qualification, regeneration.
- **No reboot within a group.** The launcher requires the same boot for a group's qualification and its regeneration.

## Stopping rules (fixed in advance)

1. **When qualification fails, that group's regeneration does not start.** Qualification fails if:
   - the status is not `QUALIFICATION_EVIDENCE_COMPLETE`;
   - the audit is not `CAPTURED_REPEATS_MATCH`;
   - the open-sampling controls do not discriminate;
   - or a new relevant log event appears.
   The directory is kept, and no retry runs in it.
2. **Group B still runs if group A fails qualification.**
3. **Collector refusal.** If the collector refuses because the oldest retained record carries another computer name (seen on host 2 on 19 November), nothing is patched on site. A follow-up record is written and pushed first. Then the author decides whether to apply the host-2 patch.
4. **Retries.** Every retry uses a new directory, after a follow-up record has been pushed.
5. **The window.** A phase that would pass the end of the window is not started.

## Out of scope

- The Node exploratory replay;
- P2-A and P2-B;
- the analyses (`regen_compare_v2.py`, `two_layer_report.py` and the exploratory re-tally). These run later, read-only, on the Mac.

## Where the results go

- **Every phase directory:** archived with its SHA-256 to the author's drive.
- **Kept private:** host identities, event XML and the approval receipts.
- **Publication and the report to the supervisor:** these follow the Mac verification.
