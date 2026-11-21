# Operational settings of the approved Mac qualification

The supervisor's review of 21 November 2026 approved the one-page qualification standard
(SHA-256 `fc91f7ee…`, reply SHA-256 `527b39aa…`): two runs of the same 20 known conditions,
identical per-case verdicts, and no case ending by timeout or error. The review asks for no
further observation apparatus and no criterion that does not affect the verdict.

The watchdog values in `execution-plan.json` only stop a hung run. They are generous
multiples of the measured complete known blocks: 106 s for the live-manifest repeat and
152 s for the round-2 command extension, both on 12 November 2026.

- Each block is limited to 1,800 s, and the renderer to 600 s.
- After the block limit, the parent allows 120 s plus a 30 s shutdown grace.
- The resource bounds are set to null. The earlier swap and RSS admission thresholds do not
  enter the approved verdict.

Written by the author's assistant before any qualification run; no run has used these values.
