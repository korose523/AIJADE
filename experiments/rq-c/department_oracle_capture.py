"""Record and validate P2-R evaluator evidence without invoking an evaluator."""

from datetime import datetime
from hashlib import sha256
import json
import re

from department_oracle_evidence import (
    EVALUATOR_SCHEMA, OBSERVATIONS_SCHEMA, OBSERVATION_SCOPES, SKIPPED, VARIANTS,
    decode_evidence, derive_programs, require_fields,
)
from prepare_department_regeneration import encoded, instant, require, sha
from regen_compare_v2 import SHA256


EVENT_SCHEMA = "aijade.p2-r.department-oracle-case-event.v1"
ENVIRONMENT_SCHEMA = "aijade.p2-r.department-oracle-node-environment.v1"
INVOCATION_SCHEMA = "aijade.p2-r.department-oracle-invocation.v1"
REVIEW_SCHEMA = "aijade.p2-r.department-oracle-capture-review.v1"
CAPTURE_SCHEMA = "aijade.p2-r.department-oracle-verified-capture.v1"
ARTIFACTS = ("evaluator.bin", "node.bin")
IDENTITY_FILES = ("invocation.json", "version-before.txt", "version-after.txt",
                  "environment-before.json", "environment-after.json")
EVENTS_FILE = "case-events.jsonl"
EVALUATOR_EVENTS_FILE = "evaluator-events.jsonl"
CAPTURE_FILES = frozenset((*ARTIFACTS, *IDENTITY_FILES, EVENTS_FILE))


class CaseEventWriter:
    """Write typed event records at an evaluator's own evaluation boundaries."""

    def __init__(self, stream, session_id, evidence_scope, manifest_sha256, identity_files, started_at):
        self.stream = stream
        self.session_id = session_id
        self.sequence = 0
        self.closed = False
        self.boundary = {"evidenceScope": evidence_scope, "manifestFileSha256": manifest_sha256,
                         "identityFilesSha256": identity_files}
        self._emit("CAPTURE_START", **self.boundary, atUtc=started_at)

    def _emit(self, event, **details):
        require(not self.closed, "case event writer is already closed")
        line = {"schema": EVENT_SCHEMA, "sessionId": self.session_id, "sequence": self.sequence,
                "event": event, **details}
        self.stream.write((json.dumps(line, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode())
        self.stream.flush()
        self.sequence += 1

    def start_variant(self, group, task, digest, variant, timeout_ms):
        self._emit("VARIANT_START", group=group, taskId=task, codeSha256=digest, variant=variant, timeoutMs=timeout_ms)

    def case_result(self, case_index, binding, result, elapsed_ns):
        self._emit("CASE_RESULT", caseIndex=case_index, caseBindingSha256=binding, result=result, elapsedNs=elapsed_ns)

    def finish_variant(self, status):
        self._emit("VARIANT_FINISH", status=status)

    def skip_program(self, group, task, digest):
        self._emit("PROGRAM_SKIP", group=group, taskId=task, codeSha256=digest, status=SKIPPED)

    def finish(self, ended_at, identity_files):
        self._emit("CAPTURE_FINISH", **dict(self.boundary, identityFilesSha256=identity_files), atUtc=ended_at)
        self.closed = True


def reviewed_time(value):
    require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value),
            "capture and review timestamps must be explicit UTC")
    seconds, separator, fraction = value[:-1].partition(".")
    return datetime.fromisoformat(seconds + (separator + fraction.ljust(6, "0") if separator else "") + "+00:00")


def check_identity(documents, manifest_sha, contract, scope, *, adapted=False):
    before = documents["version-before.txt"]
    require(before == documents["version-after.txt"], "runtime version changed during the capture")
    require(re.fullmatch(rb"v\d+\.\d+\.\d+(?:[-+][A-Za-z0-9][A-Za-z0-9.+-]{0,80})?\r?\n", before),
            "runtime version file must contain one Node version line")
    version = before.decode().strip()
    environment = decode_evidence(documents["environment-before.json"])
    require(encoded(environment) == encoded(decode_evidence(documents["environment-after.json"])),
            "runtime environment changed during the capture")
    require_fields(environment, {"schema", "runtime", "runtimeVersion", "platform", "architecture", "osRelease",
                                 "locale", "timeZone"}, "runtime environment")
    require(environment["schema"] == ENVIRONMENT_SCHEMA and environment["runtime"] == "node"
            and environment["runtimeVersion"] == version and environment["platform"] in ("darwin", "linux", "win32")
            and environment["architecture"] in ("arm64", "x64")
            and all(isinstance(environment[key], str) and re.fullmatch(r"[ -~]{1,160}", environment[key])
                    for key in ("osRelease", "locale", "timeZone")),
            "runtime environment disagrees with the Node version or environment contract")
    invocation = decode_evidence(documents["invocation.json"])
    fields = {"schema", "sessionId", "evidenceScope", "arguments", "manifestFileSha256",
              "referenceReplayEngineSha256", "benchSha256"}
    require_fields(invocation, fields | ({"evaluatorInputSha256"} if adapted else set()), "evaluator invocation")
    if adapted:
        require(isinstance(invocation["evaluatorInputSha256"], str) and SHA256.fullmatch(invocation["evaluatorInputSha256"]),
                "evaluator input digest is invalid")
    require(invocation["evidenceScope"] == scope, "evaluator invocation scope differs")
    require(invocation["schema"] == INVOCATION_SCHEMA and invocation["manifestFileSha256"] == manifest_sha
            and invocation["referenceReplayEngineSha256"] == contract["referenceReplayEngineSha256"]
            and invocation["benchSha256"] == contract["benchSha256"]
            and isinstance(invocation["sessionId"], str) and SHA256.fullmatch(invocation["sessionId"])
            and type(invocation["arguments"]) is list
            and all(isinstance(arg, str) and 0 < len(arg) <= 512 and arg.isprintable()
                    for arg in invocation["arguments"]),
            "evaluator invocation disagrees with the selected manifest, bench or reference implementation")
    return environment, invocation


def verify_review(review, scope, manifest_sha, manifest_binding, actual_files):
    require_fields(review, {"schema", "evidenceScope", "binding", "manifestFileSha256", "fileSha256", "attestation"},
                   "operator review")
    require(review["schema"] == REVIEW_SCHEMA and review["evidenceScope"] == scope
            and review["binding"] == manifest_binding and review["manifestFileSha256"] == manifest_sha,
            "operator review scope, phase or manifest differs")
    require_fields(review["fileSha256"], set(actual_files), "reviewed capture files")
    require(review["fileSha256"] == actual_files, "capture files differ from the independent operator review")
    attestation = review["attestation"]
    require_fields(attestation, {"operatorId", "reviewedAtUtc", "decision"}, "operator attestation")
    require(isinstance(attestation["operatorId"], str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,79}", attestation["operatorId"])
            and attestation["decision"] == "ACCEPTED_CAPTURER_AND_EVIDENCE",
            "operator attestation decision or identity is invalid")
    return reviewed_time(attestation["reviewedAtUtc"])


def boundary(event, common, name, manifest_sha, expected_identity, scope):
    require_fields(event, common | {"atUtc", "evidenceScope", "manifestFileSha256", "identityFilesSha256"},
                   "case capture boundary")
    require(event["evidenceScope"] == scope, "capture boundary scope differs")
    require(event["event"] == name and event["manifestFileSha256"] == manifest_sha
            and event["identityFilesSha256"] == expected_identity, "capture boundary identity differs")
    return reviewed_time(event["atUtc"])


def capture_identity(files, side):
    return {"artifactSha256": files["evaluator.bin"], "runtimeSha256": files["node.bin"],
            "invocationContractSha256": files["invocation.json"], "versionSha256": files[f"version-{side}.txt"],
            "environmentSha256": files[f"environment-{side}.json"]}


def case_binding(contract, task_id, original_index):
    task = contract["tasks"][task_id]
    require(type(original_index) is int and original_index in task["caseIndices"], "unknown original case index")
    return sha(encoded({"taskId": task_id, "caseIndex": original_index, "casesSha256": task["casesSha256"]}))


def normalize_events(raw, manifest, manifest_sha, files, contract, session_id, scope):
    manifest_groups = manifest["groups"]
    expected = {(group, row["taskId"], row["codeSha256"]): row["historicalSkipApplies"]
                for group, item in manifest_groups.items() for row in item["programs"]}
    programs = {}
    active = None
    start, finish = None, None
    lines = raw.splitlines()
    require(raw.endswith(b"\n") and len(lines) >= 2, "case event capture is truncated")
    common = {"schema", "sequence", "sessionId", "event"}
    for ordinal, line in enumerate(lines):
        event = decode_evidence(line)
        require(type(event) is dict and event.get("schema") == EVENT_SCHEMA and type(event.get("sequence")) is int
                and event["sequence"] == ordinal and event.get("sessionId") == session_id,
                "case event capture sequence or session differs")
        kind = event.get("event")
        if ordinal == 0:
            start = boundary(event, common, "CAPTURE_START", manifest_sha, capture_identity(files, "before"), scope)
        elif ordinal == len(lines) - 1:
            require(active is None, "case capture ended with an open variant")
            finish = boundary(event, common, "CAPTURE_FINISH", manifest_sha, capture_identity(files, "after"), scope)
        elif kind in ("VARIANT_START", "PROGRAM_SKIP"):
            require(active is None, "case capture contains overlapping variants")
            identity = {"group", "taskId", "codeSha256"}
            fields = {"variant", "timeoutMs"} if kind == "VARIANT_START" else {"status"}
            require_fields(event, common | identity | fields, "program event")
            key = event["group"], event["taskId"], event["codeSha256"]
            require(all(isinstance(value, str) for value in key) and key in expected, "unknown evaluator program")
            skip = expected[key]
            require(skip is (kind == "PROGRAM_SKIP"), "recorded program disposition differs")
            row = programs.setdefault(key, {"taskId": key[1], "codeSha256": key[2]})
            if skip:
                require(event["status"] == SKIPPED and "status" not in row, "duplicate or invalid skip evidence")
                row["status"] = SKIPPED
            else:
                variant = event["variant"]
                require(variant in VARIANTS and variant not in row and type(event["timeoutMs"]) is int
                        and event["timeoutMs"] == contract["tasks"][key[1]]["timeoutMs"],
                        "unknown, repeated or differently timed evaluator variant")
                row["status"] = "CAPTURED"
                active = (row, variant, [])
        elif kind == "CASE_RESULT":
            require_fields(event, common | {"caseIndex", "caseBindingSha256", "result", "elapsedNs"}, "case result event")
            require(active is not None and type(event["elapsedNs"]) is int and event["elapsedNs"] >= 0,
                    "case result lacks an active variant or elapsed observation")
            require(event["caseBindingSha256"] == case_binding(contract, active[0]["taskId"], event["caseIndex"]),
                    "case event does not bind the original bench case")
            active[2].append({"caseIndex": event["caseIndex"], "result": event["result"]})
        elif kind == "VARIANT_FINISH":
            require_fields(event, common | {"status"}, "variant finish event")
            require(active is not None, "variant finish lacks a start")
            row, variant, cases = active
            row[variant] = {"status": event["status"], "cases": cases}
            active = None
        else:
            raise ValueError("unknown or misplaced case capture event")
    require(finish > start and set(programs) == set(expected), "capture interval or program population is incomplete")
    groups = {group: {"captureFilesSha256": entry["captureFilesSha256"],
                      "programs": [programs[group, row["taskId"], row["codeSha256"]] for row in entry["programs"]]}
              for group, entry in manifest_groups.items()}
    for group, observed in groups.items():
        derive_programs(observed["programs"], manifest_groups[group]["programs"], contract)
    return groups, start, finish


def read_capture_files(directory, names):
    require(directory.is_dir(), "capture directory is missing")
    hashes, documents = {}, {}
    for name in sorted(names):
        path = directory / name
        require(path.is_file() and path.resolve() == path, f"unredirected capture file is missing: {name}")
        with path.open("rb") as source:
            if name in ARTIFACTS:
                digest = sha256()
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
                require(source.tell() > 0, f"capture artifact is empty: {name}")
                hashes[name] = digest.hexdigest()
            else:
                documents[name] = source.read()
                hashes[name] = sha(documents[name])
    return hashes, documents


def read_capture(directory, operator_raw, manifest_document, manifest_raw, scope, phase_closed_at=None):
    from department_oracle_adapter import REFERENCE_ENGINE_SHA256, bridge_events, instrumented_engine

    require(isinstance(scope, str) and scope in OBSERVATION_SCOPES, "unknown replay capture scope")
    require(manifest_raw == encoded(manifest_document), "reviewed manifest bytes differ from the selected phase")
    manifest = manifest_document["manifest"]
    contract = manifest_document["ruleContract"]
    manifest_sha = sha(manifest_raw)
    sidecar = directory / EVALUATOR_EVENTS_FILE
    has_sidecar = sidecar.exists() or sidecar.is_symlink()
    files = CAPTURE_FILES | {EVALUATOR_EVENTS_FILE} if has_sidecar else CAPTURE_FILES
    hashes, documents = read_capture_files(directory, files)
    is_instrumented = hashes["evaluator.bin"] == sha(instrumented_engine())
    require(has_sidecar is is_instrumented, "instrumented evaluator and raw event stream must appear together")
    reviewed_at = verify_review(decode_evidence(operator_raw), scope, manifest_sha, manifest["binding"], hashes)
    environment, invocation = check_identity(documents, manifest_sha, contract, scope, adapted=has_sidecar)
    session_id = invocation["sessionId"]
    if has_sidecar:
        require(contract["referenceReplayEngineSha256"] == REFERENCE_ENGINE_SHA256,
                "manifest references a different evaluator")
        normalized = bridge_events(documents[EVALUATOR_EVENTS_FILE], manifest, contract, hashes, invocation)
        require(normalized == documents[EVENTS_FILE], "normalized capture differs from the evaluator event stream")
    groups, started_at, finished_at = normalize_events(documents[EVENTS_FILE], manifest, manifest_sha, hashes,
                                                       contract, session_id, scope)
    require(scope != "OPERATOR_REVIEWED_EXTERNAL_REPLAY" or phase_closed_at is not None,
            "external replay must bind the accepted regeneration closure")
    if phase_closed_at is not None:
        require(started_at >= instant(phase_closed_at), "case capture begins before regeneration closure")
    require(reviewed_at >= finished_at, "operator review precedes the end of capture")

    shared = {"evidenceScope": scope, "binding": manifest["binding"],
              "manifestSha256": manifest_document["manifestSha256"], "manifestFileSha256": manifest_sha}
    observations = {"schema": OBSERVATIONS_SCHEMA, **shared, "groups": groups}
    receipt = {"schema": EVALUATOR_SCHEMA, **shared, "observationsFileSha256": sha(encoded(observations)),
               "referenceReplayEngineSha256": contract["referenceReplayEngineSha256"],
               "groups": {group: {"captureFilesSha256": entry["captureFilesSha256"], "programCount": len(entry["programs"])}
                          for group, entry in groups.items()},
               "evaluatorIdentity": {key: value for key, value in capture_identity(hashes, "before").items()
                                     if key != "versionSha256"}}
    provenance = {"reviewedOperatorAttestationSha256": sha(operator_raw),
                  "caseEventFileSha256": hashes[EVENTS_FILE], "fileSha256": hashes,
                  "runtimeVersion": environment["runtimeVersion"], "sessionId": session_id,
                  "acceptedRegenerationClosedAtUtc": phase_closed_at,
                  "captureStartedAtUtc": started_at.isoformat(), "captureFinishedAtUtc": finished_at.isoformat()}
    if has_sidecar:
        provenance["evaluatorEventsFileSha256"] = hashes[EVALUATOR_EVENTS_FILE]
        provenance["evaluatorInputSha256"] = invocation["evaluatorInputSha256"]
    return {"schema": CAPTURE_SCHEMA, "evidenceScope": scope, "candidateExecutionsByReport": 0,
            "formalRunsStartedByReport": 0,
            "provenance": provenance,
            "observations": observations, "evaluatorReceipt": receipt}
