# P4 lock-contention diagnosis and unqualified scheduling candidate

This directory is an offline design candidate. It is outside W4, does not change
Q `147564c9db812c1a9e5ae07992d9aa282399a310`, and does not authorize a new
qualification, model, Godot, collector, API request, seed or scientific case.
The consumed P4 refusal remains immutable and `Table 7.3 = NOT_RUN`.

The first actual runtime observation held the shared capture lock for
1.437295779 seconds. The concurrent block launch exhausted the unchanged
1.25-second acquisition bound before `Popen`: its recorded child PID is null,
ready bytes are zero and no finite lease was registered. That launch-refusal
event then correctly makes the first runtime observation and final lifecycle
registry adverse. The full observation itself took 1.635240232 seconds, below
2.5 seconds. Native/API evidence was collected; memory/swap did not cause this
particular refusal. The generic final cleanup reason is not a surviving-child
witness: all 1,476 recorded finite leases have actual wait-zero events, with no
remaining, unresolved or unleased-discovered identities in the final record.
This is not a certificate that the whole host was process-clean.

Both the sequence controller and block controller create a two-second
`MacMonitor` using the same whole-observation capture lock. Moving the initial
launch before the first sample, or waiting for one sample, does not solve that
ongoing nested contention. Repeating the observed critical service for two
streams demands 2.874591558 seconds of serial capture per two-second nominal
period, a utilization of 1.437295779 before finite launches. One measured point
is not a hardware WCET estimate or a universal future lower bound; it is already
a concrete allowed-service counterexample to a general schedulability claim.

The E02 engineering acceptance remains valid in its stated scope: one controller
and its one full observation stream, including two controlled tail samples.
It did not exercise the scientific parent plus child observation topology.
Its PASS must not be relabeled as full nested-business concurrency equivalence.

`locked_schedule_candidate.py` implements two process-free components:

- A fixed-grid serialized-server trace retains requested entry, actual lock
  acquisition, release, completion and refusal. Waiting remains inside the
  unchanged 1.25-second coordination and 2.5-second complete-observation gates.
- A fail-closed cooperative stage prototype refuses a declared capture profile
  whose nominal serial demand exceeds one. For a synthetic single-stream
  envelope with sufficient slack, it admits finite work only if its complete
  declared reservation fits before the next absolute sample slot. Queue clocks
  are explicit, intent-to-dispatch is conservatively bounded by 1.25 seconds,
  and pending work at the fixed end is a refusal. It neither hides elapsed time
  nor shifts sample clocks to a later grant. Multi-scope live coordination is
  explicitly unimplemented even for a numerically feasible dummy envelope.

This is a minimal safety direction, not a working solution for the actual
dual-monitor workload. The actual repeated two-stream profile must be refused
by the candidate. No live adapter, broker process, cross-process token protocol
or production scheduler is implemented. Passing these pure fixtures does not
make the scientific backend usable.

The tests also execute the frozen original `capture_lock` function with every
clock, descriptor and flock operation replaced by deterministic fakes. They do
not open a real lock file or launch a process. This isolates the original
timeout behavior while preserving its source function and all original limits.

Any future repair needs a separate prospective plan and source freeze. Before
another qualification, an engineering workload must include both real monitor
scopes, phase handoff, continuous child preflight/launch/register/release/wait,
all callback and writer cost, between-block work and cleanup, with the original
absolute schedule, complete raw populations, 1.25/2.5/3-second gates, exact reads
and independent replay. A new acceptance cannot come from reusing this P4 run.

Possible research directions remain unresolved: reduce complete serial capture
service with independently tested exact-read behavior; or introduce one physical
capture actor and explicitly version per-scope projections, RSS ownership,
ancestry and cleanup audits. Sharing one frame must not be counted as two
independent observations. Changing the observation/ownership protocol requires
new engineering validation; it cannot inherit E02's frozen-core acceptance.
Separate locks, silent outer-monitor removal, a larger timeout, a delayed
timestamp, retry-until-lucky, and replacing unknown evidence by zero are not
implemented or proposed as accepted fixes.
