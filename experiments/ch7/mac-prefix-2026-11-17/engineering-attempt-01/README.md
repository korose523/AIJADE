# Refused engineering attempt 01: records-only archive verification

This directory preserves the first prefix-cost engineering attempt. The packet
records ten raw observer PASS samples, nine complete-service phase acceptances,
and a tenth full service of 2.042617058 seconds exceeding its frozen two-second
engineering limit. The actual parent waits for controller exit 1; all seventy
managed finite helpers have parent-waited exit 0. These are different outcomes.
No scientific qualification, admission, rendered case, model request, new case
or seed follows. Table 7.3 remains `NOT_RUN`.

The original packet manifest is pinned to
`cda30ac1543b9514199906859579216ddd317d9997b2c28c4786a23a7fbf9e53`.
The execution source is B5
`b5af85f7a1b5f1da3ceeda0a9c1a64393a0e3efb`; its prior engineering identity
publication is F
`bb2c25b808c1c3f604e081b5fa4da4d4f76af84d`. The verifier requires those Git
objects, reads only fixed blobs with `git show`, and materializes the 28 frozen
source files into a small temporary cache. It never imports current E03 code
for this old result and does not create a full checkout.

```sh
python -B experiments/ch7/mac-prefix-2026-11-17/engineering-attempt-01/verify_archive.py \
  --repo . --output "$RUNNER_TEMP/engineering01-records.json" --controls
```

CI must fetch B5 and F before this command; the verifier never fetches or uses
credentials. Python 3.12 and the dependencies already required by the frozen
lifecycle modules are sufficient; no Godot, Ollama, macOS SDK or live service
is required. On macOS use the project runtime wrapper, an output under AIJADE,
and a project temporary directory. On CI, `RUNNER_TEMP` or `TMPDIR` supplies
the temporary location. `--temp-root` may set it explicitly.

Every physical payload and every losslessly compressed logical stream is
verified before parsing, including the complete file/directory population and
the three empty prepared logs. The original 47-field numeric object and its
types are compared with independently recomputed terminal facts. Each of the
three disposable corruption controls first accepts its complete baseline,
changes actual bytes, coherently rebinds all affected packet hashes, proves
the altered physical/logical closure, and requires semantic rejection. These
are archive controls, not the unrun live-block corruption controls.

The old Mac refusal auditor and its pre-window helper remain unchanged. An
explicit, source-SHA-pinned and counted in-memory AST adapter removes only
current host-file hash rechecks for the original interpreter, runtime wrapper,
launcher path and native binary. The native local/report variable is renamed
`recordedNativeBinarySha256`; no `file_sha` result is fabricated and no SDK or
binary file is fabricated. Complete source/Git blob, raw native/API record,
lifecycle, time, parent-wait and terminal predicates remain. The old complete
362-sample acceptance entry point is never invoked to accept this refusal.

The new output is **records-only**. It explicitly reports current native,
interpreter and host-tool physical bytes as `NOT_RECHECKED_RECORDS_ONLY`.
The original Mac audit's physical checks are retained as historical recorded
evidence, separately from this new portable replay. A records-integrity PASS
leaves engineering acceptance/completion and every scientific, hardware,
human-review and held-out qualification gate false. There are no observer,
native-helper, API, model, renderer, case or other runtime calls; process
creation in the verifier is restricted to the declared local `git show` reads.
