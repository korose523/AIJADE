The archive tools replay the one terminal refusal. A successful tool exit means
`terminalRecordIntegrityAccepted=true`; `fullQualified` remains false. They do
not run an observer, a native census, an API request, renderer, model, admission
or qualification window. The 19 planned live corruption controls remain
`NOT_RUN` and are unrelated to the 12 archive corruption controls here.

`audit.py --root PACKET --repo FROZEN_Q --output NEW_JSON` verifies the closed
manifest population, both compressed and uncompressed SHA-256/size, unique
plain-or-gzip logical representation, Q/B/P Git blobs and trees, 14 source
files, 331 original source identities, the preserved 85- and 71-file earlier
packets, the 12,352-fact original baseline, and the fixed 20 known inputs.
It checks publication/build/CI/launch identities and ordering, absence of new
seed or workload outputs, the prepared but empty admission log, partial
294/293/300 counts, and all actual terminal clocks through independent replay.
Counter fields use strict integer types; false cannot substitute for zero.

`terminal_replay.py` is a portable adaptation of the separately retained first
full replay script. It materializes lossless logical qualification bytes under
`PACKET.parent`, reuses the original predicate without editing frozen Q source,
and retains the frozen runtime-auditor domain refusal. That runtime predicate
requires a persistent runtime root; the saved idle roots are not rewritten to
make it pass. The original first replay script/report/checkpoint remain separate
evidence. Materialized temporary files are removed after reading; replay-error
checkpoint details are included in a rejected audit result.

`refusal_negative_controls.py --root PACKET --repo FROZEN_Q --output NEW_DIR`
creates 12 independent archive copies. Each copy must first accept the
unchanged terminal record. Every mutation must change actual file bytes, and
the complete manifest is then rebound to those bytes before rejection is
tested. A no-op control is an error. Original packet fingerprints are compared
after every control. Hard-linked copies use atomic inode replacement for all
writes; the original shared inode is never modified.

The first baseline executes all 294 expensive sample predicates. In the same
process, later baseline copies may reuse successful predicates only when the
actual canonical raw sample, actual complete and prefix journal SHA, policy
bytes, all 14 frozen source bytes, adapter bytes and original replay source
identity are equal. Cross-sample prefix order, capture lease uniqueness and all
terminal predicates remain outside this cache. A changed raw sample misses the
cache and executes its predicate. Cache state is held in trusted process memory;
no packet-provided JSON result or claimed hash supplies a cache entry.

Run using the project's existing Python environment through its local wrapper
so caches and temporary files remain inside AIJADE. `--output` must be new and
outside the immutable packet. Use the controls command first to obtain the
first full replay and the 12 baseline checks in a single process; invoking
another standalone process intentionally has no cache from that run.

Only exact registered PID/creation-time absence evidence from the prior
post-stop analysis is archived. These tools make no new process census, inspect
no credentials or unrelated argv/environment, and send no signals. Git commands
read fixed local objects and do not contact a remote.
