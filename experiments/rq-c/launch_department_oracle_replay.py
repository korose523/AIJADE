#!/usr/bin/env python3
"""Launch the reviewed P2-R Node oracle once after accepted regeneration."""

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

from department_oracle_adapter import bridge_events, instrumented_engine
from department_oracle_capture import (
    ENVIRONMENT_SCHEMA, EVENTS_FILE, INVOCATION_SCHEMA, check_identity, normalize_events, read_capture_files,
)
from department_oracle_evidence import decode_evidence
from department_oracle_process import (
    APPROVAL_FILE, COMPLETE, INPUT_FILE, PROCESS_FILE, PROCESS_SCHEMA, RAW_EVENTS_FILE, REFUSED,
    STDOUT_FILE, STREAM_FILES, ordered_programs, process_binding, streams, validate_input, validate_stdout,
    verify_execution_approval,
)
from launch_department_regeneration import APPROVAL as REGENERATION_APPROVAL, digest_file, file_pin, inside, now, stamp, write
from oracle_audit import BENCH, BENCH_SHA256
from prepare_department_regeneration import REPO, encoded, instant, prepare, require, sha
from regen_compare_v2 import SHA256
from rescore_department_oracle import accepted_population, local_file, pinned_bytes, report_header, rule_contract


EXTERNAL = "OPERATOR_REVIEWED_EXTERNAL_REPLAY"
NODE_ENV = {"LC_ALL": "C", "LANG": "C", "TZ": "UTC"}
NODE_SNAPSHOT = """
const {locale, timeZone} = new Intl.DateTimeFormat().resolvedOptions();
process.stdout.write(JSON.stringify({runtime: 'node', runtimeVersion: process.version, platform: process.platform,
  architecture: process.arch, osRelease: require('node:os').release(), locale, timeZone}));
"""


def accepted_inputs(bundle, phase_pin, manifest_raw, worklist, contract):
    manifest, groups = accepted_population(bundle, phase_pin, worklist, contract)
    document = dict(report_header(worklist, contract), scope="REPLAY_MANIFEST_ONLY", manifest=manifest,
                    manifestSha256=sha(encoded(manifest)))
    require(manifest_raw == encoded(document), "reviewed manifest differs from the accepted regeneration population")
    phase = decode_evidence(pinned_bytes(bundle / "phase-result.json", phase_pin, "regeneration phase"))
    return document, groups, phase["observationFinishedAt"], phase["approvalSha256"]


def build_input(manifest_document, groups, tasks, scope, session):
    require(isinstance(session, str) and SHA256.fullmatch(session), "invalid replay session identity")
    manifest, contract = (manifest_document[key] for key in ("manifest", "ruleContract"))
    pairs = []
    for group, pinned in ordered_programs(manifest):
        task, digest = pinned["taskId"], pinned["codeSha256"]
        skills = groups[group][1][task, digest]
        code = skills[0].identity[4]
        require(sha(code.encode()) == digest and all(skill.identity[4] == code for skill in skills),
                "admitted candidate code identity differs")
        pairs.append([task, code])
    context = {"evidenceScope": scope, "sessionId": session, "manifestFileSha256": sha(encoded(manifest_document))}
    raw = json.dumps({"tasks": tasks, "pairs": pairs, "dropped": contract["removedCaseArgs"],
                      "observationContext": context}, ensure_ascii=True, sort_keys=True, allow_nan=False).encode()
    invocation = {"schema": INVOCATION_SCHEMA, **context, "arguments": [], "evaluatorInputSha256": sha(raw),
                  "referenceReplayEngineSha256": contract["referenceReplayEngineSha256"],
                  "benchSha256": contract["benchSha256"]}
    validate_input(raw, manifest, contract, invocation)
    return raw, invocation


def reviewed_approval(path, approval, original, original_sha, invocation, manifest, artifact_sha, close, head):
    verify_execution_approval(approval, invocation, manifest, artifact_sha, approval["node"]["sha256"])
    require(approval["evidenceScope"] == EXTERNAL and approval["sourceCommit"] == head
            and approval["hostName"] == socket.gethostname(), "replay approval binds a different scope, checkout or host")
    supervisor = approval["supervisorReply"]
    plan = approval["approvedPlan"]
    require(approval["regenerationApprovalSha256"] == original_sha
            and original["schema"] == REGENERATION_APPROVAL and original["scope"] == "P2-R-department"
            and "regeneration" in original["phases"]
            and original["sourceCommit"] == manifest["binding"]["sourceCommit"]
            and original["worklistSha256"] == manifest["binding"]["worklistSha256"]
            and all(supervisor[key] == original["supervisorReply"][key] for key in ("sha256", "reviewedSender", "receivedAt"))
            and plan["sha256"] == original["approvedPlan"]["sha256"],
            "replay approval does not carry forward the accepted P2-R plan and supervisor reply")
    for item in (supervisor, plan):
        require(file_pin(inside(path.parent, item["path"]), item["sha256"]).stat().st_size > 0,
                "approved reply or plan is empty")
    start, end = instant(approval["notBefore"]), instant(approval["notAfter"])
    require(instant(close) <= start and instant(supervisor["receivedAt"]) <= start <= now() < end,
            "the accepted regeneration, reply or approved allocation does not permit replay")
    node = Path(approval["node"]["path"])
    require(node.is_absolute() and node.resolve() == node and os.access(node, os.X_OK),
            "approved Node runtime must be a resolved executable")
    return file_pin(node, approval["node"]["sha256"])


def runtime_snapshot(node, directory, deadline):
    def get(*args):
        wait = (deadline - now()).total_seconds()
        require(wait > 0, "approved replay window elapsed")
        done = subprocess.run([str(node), *args], cwd=directory, env=NODE_ENV, stdin=subprocess.DEVNULL,
                              capture_output=True, check=True, timeout=min(15, wait))
        require(done.stderr == b"", "Node runtime probe returned unexpected diagnostics")
        return done.stdout

    version = get("--version")
    environment = dict(decode_evidence(get("-e", NODE_SNAPSHOT)), schema=ENVIRONMENT_SCHEMA)
    require(version.decode().strip() == environment["runtimeVersion"], "observed Node version differs")
    return version, environment


def run_process(node, directory, deadline):
    """Retain both streams directly and keep the actual exit status after termination."""
    result = {"processStarted": False, "termination": "NOT_STARTED", "exitCode": None, "error": None,
              "startedAtUtc": None, "finishedAtUtc": None}
    with (directory / INPUT_FILE).open("rb") as payload, (directory / STDOUT_FILE).open("wb") as out, \
            (directory / RAW_EVENTS_FILE).open("wb") as errors:
        try:
            launch_start = now()
            require(launch_start < deadline, "approved replay window elapsed")
            proc = subprocess.Popen([str(node), str(directory / "evaluator.bin")], cwd=directory, env=NODE_ENV,
                                    stdin=payload, stdout=out, stderr=errors, start_new_session=os.name == "posix")
        except (OSError, ValueError, KeyboardInterrupt) as exc:
            result["error"] = str(exc) or type(exc).__name__
            return result
        result.update(processStarted=True, startedAtUtc=stamp(launch_start), termination="EXITED")
        try:
            proc.wait(timeout=max(0, (deadline - now()).total_seconds()))
        except (subprocess.TimeoutExpired, KeyboardInterrupt, OSError) as exc:
            reason = ("TIMEOUT" if isinstance(exc, subprocess.TimeoutExpired) else
                      "INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "WAIT_ERROR")
            result.update(termination=reason, error=type(exc).__name__)
            try:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                proc.wait(timeout=5)
            except (subprocess.TimeoutExpired, KeyboardInterrupt, OSError):
                result.update(termination="REAP_UNVERIFIED")
        result.update(exitCode=proc.returncode, finishedAtUtc=stamp(now()))
    return result


def staged_replay(directory, manifest_document, payload, invocation, approval_raw, node, close):
    """Record one authorized attempt; failures keep their raw streams and receipt."""
    approval = decode_evidence(approval_raw)
    manifest, contract = (manifest_document[key] for key in ("manifest", "ruleContract"))
    artifact = instrumented_engine()
    node_sha = approval["node"]["sha256"]
    verify_execution_approval(approval, invocation, manifest, sha(artifact), node_sha)
    validate_input(payload, manifest, contract, invocation)
    require(approval["hostName"] == socket.gethostname()
            and instant(close) <= instant(approval["notBefore"]) <= now() < instant(approval["notAfter"]),
            "the approved replay host or execution window differs")
    file_pin(node, node_sha)
    directory.mkdir(mode=0o700, exist_ok=False)
    (directory / APPROVAL_FILE).write_bytes(approval_raw)
    (directory / INPUT_FILE).write_bytes(payload)
    (directory / "evaluator.bin").write_bytes(artifact)
    write(directory / "invocation.json", invocation)
    for name in (STDOUT_FILE, RAW_EVENTS_FILE):
        (directory / name).touch(exist_ok=False)
    deadline = instant(approval["notAfter"])
    receipt = {"schema": PROCESS_SCHEMA, "status": REFUSED, **process_binding(approval, invocation, manifest),
               "executionApprovalSha256": sha(approval_raw), "invocationContractSha256": sha(encoded(invocation)),
               "processStarted": False, "termination": "NOT_STARTED", "exitCode": None,
               "hostName": socket.gethostname(), "startedAtUtc": None, "finishedAtUtc": None, "error": None,
               "stdoutReadback": None}
    try:
        shutil.copyfile(node, directory / "node.bin")
        file_pin(directory / "node.bin", node_sha)
        file_pin(node, node_sha)
        version, environment = runtime_snapshot(node, directory, deadline)
        require(encoded(environment) == encoded(approval["node"]["environment"]), "Node environment differs from approval")
        (directory / "version-before.txt").write_bytes(version)
        write(directory / "environment-before.json", environment)
        receipt.update(run_process(node, directory, deadline))
        require(receipt["termination"] == "EXITED" and type(receipt["exitCode"]) is int and receipt["exitCode"] == 0,
                f"evaluator process {receipt['termination']} with exit {receipt['exitCode']}")
        file_pin(node, node_sha)
        version, environment = runtime_snapshot(node, directory, deadline)
        (directory / "version-after.txt").write_bytes(version)
        write(directory / "environment-after.json", environment)
        names = {"node.bin", "evaluator.bin", "invocation.json", "environment-before.json", "environment-after.json",
                 "version-before.txt", "version-after.txt", *STREAM_FILES}
        hashes, documents = read_capture_files(directory, names)
        require(hashes["evaluator.bin"] == sha(artifact) and hashes["node.bin"] == node_sha,
                "frozen artifacts changed during replay")
        _, verified = check_identity(documents, invocation["manifestFileSha256"], contract,
                                     invocation["evidenceScope"], adapted=True)
        require(verified == invocation, "invocation contract changed during replay")
        normalized = bridge_events(documents[RAW_EVENTS_FILE], manifest, contract, hashes, invocation)
        groups, start, end = normalize_events(normalized, manifest, invocation["manifestFileSha256"], hashes,
                                              contract, invocation["sessionId"], invocation["evidenceScope"])
        require(instant(receipt["startedAtUtc"]) <= start < end <= instant(receipt["finishedAtUtc"]) <= deadline,
                "evaluator event closure falls outside the observed process")
        data = validate_input(documents[INPUT_FILE], manifest, contract, invocation)
        receipt["stdoutReadback"] = validate_stdout(documents[STDOUT_FILE], manifest, groups, data["tasks"], contract)
        receipt["fileEvidence"] = streams(documents)
        (directory / EVENTS_FILE).write_bytes(normalized)
        receipt["status"] = COMPLETE
    except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError, KeyboardInterrupt) as exc:
        receipt["error"] = receipt["error"] or str(exc) or type(exc).__name__
    if "fileEvidence" not in receipt:
        receipt["fileEvidence"] = streams({name: (directory / name).read_bytes() for name in STREAM_FILES})
    write(directory / PROCESS_FILE, receipt)
    return receipt


@contextmanager
def reserve_session(manifest_pin, session):
    directory = REPO / ".runtime" / "p2-r-replay-sessions"
    directory.parent.mkdir(exist_ok=True)
    directory.mkdir(exist_ok=True)
    require(directory.resolve() == directory, "replay session registry is redirected")
    marker = directory / sha(encoded({"manifest": manifest_pin, "session": session}))
    with marker.open("xb") as stream:
        stream.write(b"reserved\n")
    yield


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="action", required=True)
    for action in ("plan", "run"):
        command = modes.add_parser(action)
        command.add_argument("--regeneration-bundle", type=Path, required=True)
        command.add_argument("--phase-receipt-sha256", required=True)
        command.add_argument("--replay-manifest", type=Path, required=True)
        command.add_argument("--replay-manifest-sha256", required=True)
        if action == "plan":
            command.add_argument("--session-id", required=True)
        else:
            command.add_argument("--approval", type=Path, required=True)
            command.add_argument("--approval-sha256", required=True)
            command.add_argument("--regeneration-approval", type=Path, required=True)
            command.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    try:
        bundle = local_file(args.regeneration_bundle, "regeneration bundle")
        manifest_raw = pinned_bytes(args.replay_manifest, args.replay_manifest_sha256, "replay manifest")
        document, groups, closed, original_sha = accepted_inputs(bundle, args.phase_receipt_sha256, manifest_raw,
                                                                 prepare(), rule_contract())
        raw_bench = pinned_bytes(REPO / BENCH, BENCH_SHA256, "pinned replay bench")
        tasks = {item["id"]: {"tests": item["tests"], "timeoutMs": item.get("timeoutMs")}
                 for item in decode_evidence(raw_bench)["tasks"]}
        artifact_sha = sha(instrumented_engine())
        if args.action == "plan":
            _, invocation = build_input(document, groups, tasks, EXTERNAL, args.session_id)
            result = {"status": "REPLAY_INPUT_PLAN_ONLY", "processesStarted": 0, "evaluatorSha256": artifact_sha,
                      "binding": document["manifest"]["binding"], "invocation": invocation,
                      "regenerationApprovalSha256": original_sha}
            sys.stdout.buffer.write(encoded(result))
            return 0
        approval_path = local_file(args.approval, "reviewed replay approval")
        approval_raw = pinned_bytes(approval_path, args.approval_sha256, "reviewed replay approval")
        approval = decode_evidence(approval_raw)
        original = decode_evidence(pinned_bytes(args.regeneration_approval, original_sha, "accepted regeneration approval"))
        payload, invocation = build_input(document, groups, tasks, EXTERNAL, approval["sessionId"])
        destination = local_file(args.bundle, "new replay evidence directory")
        require(destination.parent.is_dir() and not destination.exists() and not destination.is_relative_to(bundle)
                and (not destination.is_relative_to(REPO) or destination.is_relative_to(REPO / ".runtime")),
                "choose a new AIJADE-local replay bundle outside the regeneration and tracked checkout")
        git = ["git", "-C", str(REPO)]
        head = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
        require(not subprocess.check_output([*git, "status", "--porcelain=v1", "--untracked-files=all"]),
                "the source checkout must be clean")
        node = reviewed_approval(approval_path, approval, original, original_sha, invocation, document["manifest"],
                                 artifact_sha, closed, head)
        with reserve_session(invocation["manifestFileSha256"], invocation["sessionId"]):
            receipt = staged_replay(destination, document, payload, invocation, approval_raw, node, closed)
        sys.stdout.buffer.write(encoded({"status": receipt["status"], "processStarted": receipt["processStarted"],
                                         "exitCode": receipt["exitCode"],
                                         "processReceiptSha256": digest_file(destination / PROCESS_FILE)}))
        return 0 if receipt["status"] == COMPLETE else 1
    except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    sys.exit(main())
