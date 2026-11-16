# Mac bulk refusal archive: portable audit handoff

The immutable packet contains 71 payload files plus its manifest. The core audit
accepts terminal record integrity only. It does not accept qualification or create
a new admission, model call, renderer session, seed, case or comparison result.

Fixed packet manifest SHA256:
`04897ab29eb5eca4b47d4d0aef872777497cd627e4ebcfa99b796f851ff46c1a`.
Fixed `packet/audit/independent-refusal-audit.json` SHA256:
`a029d58b66e3e0c4c5bf32e3558ced84706478d6f28b2a20a8d854d015ad6905`.

`audit.py` and `refusal_negative_controls.py` must be adjacent in the published
archive. The packet is `packet/`. Keep the controls code, execution logs and
control result JSON **beside** the packet, not inside it: the control report binds
the baseline manifest hash and must not become a self-referential manifest input.
All gzip logical bytes are preserved with mtime zero. Do not regenerate or amend
the packet after these final controls without rebinding and rerunning them.

## Git objects needed before offline audit

These immutable commits must already exist in the local repository. The auditor
never fetches or authenticates:

- Q: `d96152b98f61e3cb47db9ec3d95e00591830d024`
- B: `a20f090423548dedbf1337ec50786daa9e2d028a`
- public plan P: `82cfaa2fd4ff7810cab09012829e5b8d7a2c82c9`
- research introduction H: `3e37a85b5bb39669782543fc7197d73eecf2dc1f`
- unchanged historical base: `2d52777bc6b34fd8c6410800f0c56268d8132301`

CI preparation may use a full checkout or explicitly fetch these five public Git
objects before running the offline scripts. A shallow checkout containing only
the archive commit is insufficient. The scripts only require Python standard
library and Git. They do not require psutil, .NET, Docker, Mac APIs, the Mach-O
helper, a local Ollama service or private renderer/model assets at replay time.

## Linux CI commands

From the repository containing the published archive, use explicit paths:

```sh
mkdir -p .runtime/mac-bulk-refusal
python3 experiments/ch7/mac-census-2026-11-16/audit.py \
  --root experiments/ch7/mac-census-2026-11-16/packet \
  --repo . \
  --output .runtime/mac-bulk-refusal/audit.json
python3 experiments/ch7/mac-census-2026-11-16/refusal_negative_controls.py \
  --root experiments/ch7/mac-census-2026-11-16/packet \
  --repo . \
  --output .runtime/mac-bulk-refusal/controls.json \
  --temp-root .runtime/mac-bulk-refusal/disposable
```

The explicit CLI does not create `/Volumes/` on Linux. `--output` and disposable
`--temp-root` are required to stay outside the immutable packet. Each corruption
starts from the full valid baseline, rewrites physical/logical manifest hashes,
and verifies that changed content was not a no-op before semantic refusal. Only
immutable `(repo, commit, path)` Git blob bytes are cached; packet reads, manifest
checks, native parsing, process replay and derived metrics are recomputed.

## Publication and evidence limits

Git may ignore logs, binaries or outputs. Explicitly force-add all 71 packet
payloads plus the manifest and independently verify their **tracked Git blob**
population and physical/logical bytes; a disk-only manifest check is insufficient
for publication. Preserve all engineering failures and excluded first attempts.
There are no large DLL or private PMX files in this packet. Native helper bytes
are original owned evidence and are never executed by replay.

The final controller after-snapshot FAIL and null RSS remain unchanged. Its
reparent labels arise from missing-root/empty-closure cascade, while surviving
controllers keep their original identities and parents in raw graphs. The
3.6311725030245725-second settling/admission gap independently violates Q's
three-second whole-sequence rule. Keep original twenty **unknown** dispositions.
No block output or case evidence exists; Q ordering supports a separately
labelled inference about not reaching flow/renderer, not full machine history.

Local post-run receipts bind 576 actual binary hashes and 331 actual protected
source hashes to Q/B. Nineteen explicitly recorded owned identities are absent;
this does not prove cleanup of unobserved processes or the whole machine. CI can
validate those receipt bindings and raw observations but cannot re-observe the
original Mac. Formal backend qualification, fresh held-out completion, independent
human review and current-product inheritance remain false; Table 7.3 is NOT_RUN.

CI isolates the exact Q checkout under `.runtime/ch7-mac-bulk-source` and passes that path with `--repo`; the product and archive are not requalified by replay. The directly named example above assumes a Q-identical observer working copy.
