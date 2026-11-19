"""Attach per-case evidence to the existing P2-R Node replay without launching it."""

import argparse
from io import BytesIO
from pathlib import Path
import sys

from department_oracle_capture import (
    CAPTURE_FILES, EVALUATOR_EVENTS_FILE, EVENTS_FILE, CaseEventWriter, capture_identity,
    case_binding, check_identity, normalize_events, read_capture_files,
)
from department_oracle_evidence import OBSERVATION_SCOPES, VARIANTS, decode_evidence, require_fields
from oracle_audit import NODE_REPLAY
from prepare_department_regeneration import HERE, encoded, require, sha


OBSERVATION_SCHEMA = "aijade.p2-r.department-oracle-evaluator-event.v1"
REFERENCE_SOURCE_SHA256 = "d790d9ddaa8a7425d0b8bc945e97007dce8c96d94444be47ab0fbda08275a349"
REFERENCE_ENGINE_SHA256 = "f30dc04f35c8c0590a764b07c526c5bc080629d7923bcc50f0f80a087423a3c1"

OBSERVER = """
const observationHash = value => require('node:crypto').createHash('sha256').update(value).digest('hex');
let observationSequence = 0;
function observe(event, details) {
  const row = {schema: '__OBSERVATION_SCHEMA__', sequence: observationSequence++, event, ...details};
  require('node:fs').writeSync(2, JSON.stringify(row) + '\\n');
}
function observedVariant(pair, task, variant, code, lexical, drop) {
  const identity = {...pair, variant};
  const cases = task.tests.map(c => ({args: c.args, expected: c.expected}));
  const caseIndices = task.tests.flatMap((c, i) => drop.includes(c.args) ? [] : [i]);
  observe('VARIANT_START', {...identity, timeoutMs: task.timeoutMs ?? 2000, caseIndices,
    casesSha256: observationHash(JSON.stringify(cases, null, 2) + '\\n')});
  return run(code, task, lexical, drop, {
    result(caseIndex, result, started) {
      observe('CASE_RESULT', {...identity, caseIndex, result, elapsedNs: Number(process.hrtime.bigint() - started)});
    },
    finish(status) { observe('VARIANT_FINISH', {...identity, status}); }
  });
}
"""


def replace_once(source, old, new):
    require(source.count(old) == 1, "pinned evaluator observation point changed")
    return source.replace(old, new)


def instrumented_engine():
    """Return the pinned evaluator with observers; do not read inputs or start Node."""
    require(sha((HERE / "oracle_audit.py").read_bytes()) == REFERENCE_SOURCE_SHA256
            and sha(NODE_REPLAY.encode()) == REFERENCE_ENGINE_SHA256, "archived evaluator identity changed")
    source = NODE_REPLAY
    substitutions = (
        ("function run(code, task, lexical, drop) {", "function run(code, task, lexical, drop, observer) {"),
        ("  if (!r.ctx) return { ok: false, via: null, failing: [], error: r.error };",
         "  if (!r.ctx) {\n"
         "    observer.finish(r.error === 'no callable' ? 'NO_CALLABLE' : 'SETUP_ERROR');\n"
         "    return { ok: false, via: null, failing: [], error: r.error };\n"
         "  }"),
        ("  for (const c of task.tests) {\n    if (drop.includes(c.args)) continue;\n    try {",
         "  let caseIndex = -1;\n"
         "  for (const c of task.tests) {\n"
         "    caseIndex++;\n"
         "    if (drop.includes(c.args)) continue;\n"
         "    const started = process.hrtime.bigint();\n"
         "    let result = 'PASS';\n"
         "    try {"),
        ("      if (!deepEqual(got, want)) failing.push({ args: c.args, expected: c.expected, actual: got === undefined ? 'undefined' : JSON.stringify(got) });",
         "      if (!deepEqual(got, want)) {\n"
         "        result = 'FAIL';\n"
         "        failing.push({ args: c.args, expected: c.expected, actual: got === undefined ? 'undefined' : JSON.stringify(got) });\n"
         "      }"),
        ("      if (String(e).includes('Script execution timed out')) return { ok: false, via: r.via, failing, error: 'timeout' };\n"
         "      failing.push({ args: c.args, expected: c.expected, threw: String(e).slice(0, 90) });\n"
         "    }\n  }\n",
         "      if (String(e).includes('Script execution timed out')) result = 'TIMEOUT';\n"
         "      else {\n"
         "        result = 'FAIL';\n"
         "        failing.push({ args: c.args, expected: c.expected, threw: String(e).slice(0, 90) });\n"
         "      }\n"
         "    }\n"
         "    observer.result(caseIndex, result, started);\n"
         "    if (result === 'TIMEOUT') {\n"
         "      observer.finish('CASE_RESULTS');\n"
         "      return { ok: false, via: r.via, failing, error: 'timeout' };\n"
         "    }\n"
         "  }\n"
         "  observer.finish('CASE_RESULTS');\n"),
        ("let src = '';",
         OBSERVER.replace("__OBSERVATION_SCHEMA__", OBSERVATION_SCHEMA) + "\nlet src = '';"),
        ("process.stdin.on('data', d => src += d);",
         "const observationInputHash = require('node:crypto').createHash('sha256');\n"
         "process.stdin.on('data', d => { observationInputHash.update(d); src += d; });"),
        ("  const { tasks, pairs, dropped } = JSON.parse(src);",
         "  const { tasks, pairs, dropped, observationContext } = JSON.parse(src);\n"
         "  const {sessionId, evidenceScope, manifestFileSha256} = observationContext;\n"
         "  const observedRun = {programCount: pairs.length, sessionId, evidenceScope, manifestFileSha256,\n"
         "    evaluatorInputSha256: observationInputHash.digest('hex')};"),
        ("  const out = pairs.map(([id, code]) => {\n"
         "    if (RISKY.test(code)) return { skipped: true };\n"
         "    const task = tasks[id];\n"
         "    return { asRun: run(code, task, false, []), entry: run(code, task, true, []), entryAndTest: run(code, task, true, dropped[id] ?? []) };\n"
         "  });\n"
         "  process.stdout.write(JSON.stringify(out));",
         "  observe('REPLAY_START', {...observedRun, atUtc: new Date().toISOString()});\n"
         "  const out = pairs.map(([id, code], pairIndex) => {\n"
         "    const pair = {pairIndex, taskId: id, codeSha256: observationHash(code)};\n"
         "    if (RISKY.test(code)) {\n"
         "      observe('PROGRAM_SKIP', pair);\n"
         "      return { skipped: true };\n"
         "    }\n"
         "    const task = tasks[id];\n"
         "    return {\n"
         "      asRun: observedVariant(pair, task, 'asRun', code, false, []),\n"
         "      entry: observedVariant(pair, task, 'entry', code, true, []),\n"
         "      entryAndTest: observedVariant(pair, task, 'entryAndTest', code, true, dropped[id] ?? [])\n"
         "    };\n"
         "  });\n"
         "  process.stdout.write(JSON.stringify(out));\n"
         "  observe('REPLAY_FINISH', {...observedRun, atUtc: new Date().toISOString()});"),
    )
    for old, new in substitutions:
        source = replace_once(source, old, new)
    return source.encode()


def raw_rows(raw):
    require(raw.endswith(b"\n"), "evaluator event stream is truncated")
    for number, line in enumerate(raw.splitlines()):
        row = decode_evidence(line)
        require(type(row) is dict and row.get("schema") == OBSERVATION_SCHEMA
                and type(row.get("sequence")) is int and row["sequence"] == number,
                "evaluator event stream sequence or schema differs")
        yield row


def bridge_events(raw, manifest, contract, hashes, invocation):
    """Normalize the observed engine sidecar and apply the existing capture verifier."""
    pairs = [(group, program) for group, entry in sorted(manifest["groups"].items())
             for program in entry["programs"]]
    common = {"schema", "sequence", "event"}
    rows = iter(raw_rows(raw))
    manifest_sha, scope, session_id = (invocation[name] for name in ("manifestFileSha256", "evidenceScope", "sessionId"))
    boundary = {"programCount": len(pairs), "manifestFileSha256": manifest_sha, "evidenceScope": scope,
                "sessionId": session_id, "evaluatorInputSha256": invocation["evaluatorInputSha256"]}

    def next_row(fields, identity):
        row = next(rows, None)
        require_fields(row, common | fields | set(identity), "evaluator event")
        require(all(type(row[key]) is type(value) and row[key] == value for key, value in identity.items()),
                "evaluator event is for a different program, variant, or boundary")
        return row

    first = next_row({"atUtc"}, {**boundary, "event": "REPLAY_START"})
    with BytesIO() as stream:
        writer = CaseEventWriter(stream, session_id, scope, manifest_sha, capture_identity(hashes, "before"),
                                 first["atUtc"])
        for index, (group, program) in enumerate(pairs):
            task, digest = program["taskId"], program["codeSha256"]
            key = {"pairIndex": index, "taskId": task, "codeSha256": digest}
            if program["historicalSkipApplies"]:
                next_row(set(), {**key, "event": "PROGRAM_SKIP"})
                writer.skip_program(group, task, digest)
                continue
            rule = contract["tasks"][task]
            for variant in VARIANTS:
                identity = {**key, "variant": variant}
                expected_indices = rule["entryAndTestCaseIndices" if variant == "entryAndTest" else "caseIndices"]
                begin = next_row({"caseIndices"}, {**identity, "event": "VARIANT_START",
                                 "timeoutMs": rule["timeoutMs"], "casesSha256": rule["casesSha256"]})
                require(encoded(begin["caseIndices"]) == encoded(expected_indices),
                        "evaluator used a different retained case set")
                writer.start_variant(group, task, digest, variant, rule["timeoutMs"])
                for row in rows:
                    require(all(type(row.get(key)) is type(value) and row[key] == value
                                for key, value in identity.items()), "evaluator result is for a different variant")
                    if row.get("event") == "VARIANT_FINISH":
                        require_fields(row, common | set(identity) | {"status"}, "evaluator variant finish")
                        writer.finish_variant(row["status"])
                        break
                    require_fields(row, common | set(identity) | {"caseIndex", "result", "elapsedNs"},
                                   "evaluator case result")
                    require(row["event"] == "CASE_RESULT", "misplaced evaluator case result")
                    case_index = row["caseIndex"]
                    writer.case_result(case_index, case_binding(contract, task, case_index), row["result"], row["elapsedNs"])
                else:
                    raise ValueError("evaluator event stream closed before the variant finished")
        final = next_row({"atUtc"}, {**boundary, "event": "REPLAY_FINISH"})
        require(next(rows, None) is None, "unexpected events after evaluator closure")
        writer.finish(final["atUtc"], capture_identity(hashes, "after"))
        normalized = stream.getvalue()
    normalize_events(normalized, manifest, manifest_sha, hashes, contract, session_id, scope)
    return normalized


def bridge_capture(directory, manifest_document, manifest_raw, raw_pin):
    require(manifest_raw == encoded(manifest_document), "replay manifest must use the canonical byte format")
    manifest = manifest_document["manifest"]
    contract = manifest_document["ruleContract"]
    manifest_sha = sha(manifest_raw)
    require(contract["referenceReplayEngineSha256"] == REFERENCE_ENGINE_SHA256,
            "manifest references a different evaluator")
    hashes, documents = read_capture_files(directory, (CAPTURE_FILES - {EVENTS_FILE}) | {EVALUATOR_EVENTS_FILE})
    require(hashes["evaluator.bin"] == sha(instrumented_engine()), "capture evaluator is not the instrumented artifact")
    require(hashes[EVALUATOR_EVENTS_FILE] == raw_pin, "raw evaluator event digest differs")
    scope = decode_evidence(documents["invocation.json"])["evidenceScope"]
    require(isinstance(scope, str) and scope in OBSERVATION_SCOPES, "unknown evaluator evidence scope")
    _, invocation = check_identity(documents, manifest_sha, contract, scope, adapted=True)
    return bridge_events(documents[EVALUATOR_EVENTS_FILE], manifest, contract, hashes, invocation)


def main():
    from rescore_department_oracle import local_file, pinned_bytes

    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="action", required=True)
    modes.add_parser("artifact").add_argument("--out", type=Path, required=True)
    normalize = modes.add_parser("bridge")
    normalize.add_argument("--replay-manifest", type=Path, required=True)
    normalize.add_argument("--replay-manifest-sha256", required=True)
    normalize.add_argument("--capture-directory", type=Path, required=True)
    normalize.add_argument("--evaluator-events-sha256", required=True)
    args = parser.parse_args()
    try:
        if args.action == "artifact":
            payload = instrumented_engine()
            output = local_file(args.out, "instrumented evaluator")
        else:
            directory = local_file(args.capture_directory, "capture directory")
            manifest_raw = pinned_bytes(args.replay_manifest, args.replay_manifest_sha256, "replay manifest")
            payload = bridge_capture(directory, decode_evidence(manifest_raw), manifest_raw,
                                     args.evaluator_events_sha256)
            output = directory / EVENTS_FILE
        with output.open("xb") as stream:
            stream.write(payload)
        print(sha(payload))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        parser.exit(2, f"{exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
