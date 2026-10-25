# Integrity audit of the RQ-C runs generated on the second host (plan, 25 October 2026)

**Status.** Written and committed to this repository **before** the audit below was implemented or run. It is not
registered on an external platform. It uses only recorded data: no model calls, no new generations.

**Why.** Three RQ-C runs of P2 were generated on a second host: the second-family control (llama3.1:8b) and the
prompt-template controls A and B (qwen2.5-coder 7B). The author has confirmed that this host (Windows,
RTX 5080, Intel Core i9-14900KF) is the one the author's other project excludes from research runs because its CPU has logged
errors. In those runs the runner, the sandbox, the execution oracle and the analysis ran on the main host (macOS); the
second host served only the model through Ollama (`AIJADE_OLLAMA_URL`, `run-family-gpu.sh`, `run-template.sh`). A
hardware fault on the second host could therefore change only the model's text: its generated code and its verifier
replies. This audit looks for signs of such corruption in that text.

**What it can and cannot show.** It can detect gross corruption: damaged characters, unparsable code, malformed verdicts,
or rates of these far from the same model's rates on the main host. It cannot detect a change that leaves well-formed
text, such as a different but valid token. Only a re-run on another host can rule that out; that is a new run and,
under the supervisor's schedule, waits until after 1 December and his agreement.

**Code version and deviations.** As in `2026-10-22-followup-analyses.md`: the output records the plan commit and the
code commit; any change made after this commit is listed in the output as a deviation, with its reason.

## Inputs (fixed)

The four runs, with the SHA-256 of their `trials.jsonl` and `candidates.jsonl` as pinned in
`2026-10-22-followup-analyses.md` (main run, second family, templates A and B), plus:

- the run logs `rq-c/run-family-gpu.log` and `rq-c/run-template.log`;
- the determinism pre-checks recorded on the second host: `rq-c/family-gpu/determinism-llama3.1-8b.json`,
  `determinism-llama3.1-8b-repeat.json`, `determinism-llama3.1-8b-fixedseed.json`, and
  `rq-c/template-gpu/determinism-7b-fixedseed.json`.

Host 1 (main host): `rq-c/redo/rq-c-s42-ollama-t30-r5` (qwen2.5-coder 7B, template A). Host 2: the other three runs.

## Checks

A *live generation* is a candidate record with `reused = false`. A *verifier reply* is the recorded reply of a
self-verification step: `selfReply` where the record has it, otherwise `selfRationale`.

- **A1 Character integrity.** For every live generation and every verifier reply, count texts containing U+FFFD, a
  C0 or C1 control character other than tab, line feed and carriage return, or an unpaired surrogate. On host 2,
  every hit is listed with its step and the surrounding text.
- **A2 Code extraction.** Share of live generations whose extracted `code` is empty.
- **A3 JavaScript syntax.** Share of non-empty extracted code that does not parse as a script. Parsing uses Node's
  `vm.Script` constructor, which compiles without running.
- **A4 Verdict format.** Share of verifier replies that, after trimming leading white space, begin with neither
  `PASS` nor `FAIL`. Under the runner's rule these count as FAIL.
- **A5 Run-log anomalies.** Lines of the two host-2 run logs that match `error`, `exception`, `timeout`, `fatal`,
  `unreachable`, `retry`, `stopped` or `resum`, case-insensitive. Each is listed.
- **A6 Determinism pre-checks.** The archived verdicts of the four pre-checks, as recorded.
- **A7 Same model and prompt on two hosts.** Host 1's main run against host 2's template-A run, both qwen2.5-coder 7B
  with template A. Report A1–A4 for each, with Wilson 95% intervals for the shares. Also report the verifier error
  rates already archived in `rq-c/p2-models.json` with their task-cluster intervals. These rates are known; the plan
  fixes only how they are read.

## Reading (fixed)

Different hardware gives different but legitimate text, so rates may differ between hosts. Reading rules:

- **Anomaly.** Host 2 shows an anomaly if any of the following holds:
  - A1 finds a damaged character in a host-2 text that the same pattern does not also produce on host 1;
  - for the 7B pair, the Wilson intervals of A2, A3 or A4 do not overlap;
  - A5 lists an error that is not one of the recorded, explained interruptions.
- **No anomaly.** The papers say: an audit of the second host's archived outputs found no sign of gross corruption;
  it cannot exclude changes that leave well-formed text. A re-run on another host is the remaining check.
- **Anomaly found.** The affected results are marked in the papers as needing a re-run on another host before any
  claim rests on them. They are not removed.

## Output

`rq-c/host-audit.json`, containing:

- the plan commit and the code commit;
- the input hashes as verified at run time;
- A1–A7 per run;
- the listed hits;
- the reading under the rule above.
