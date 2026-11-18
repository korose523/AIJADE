#!/usr/bin/env python3
"""Stage or launch one approved P2-R phase on the allocated department server."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

from prepare_department_regeneration import (
    DEPARTMENT_DRAFT_SHA, REPO, audit, encoded, instant, prepare, require, sha,
)
from regen_compare_v2 import INPUT_NAMES, SHA256, compare_inputs, read_inputs, validate_summary


PHASES = ("qualification", "regeneration")
LOG_CLASSES = ("system", "gpu")
APPROVAL = "aijade.p2-r.department-execution-approval.v1"
LOG_CAPTURE = "aijade.p2-r.department-log-capture.v1"
PHASE_RECEIPT = "aijade.p2-r.department-phase.v1"


def now():
    return datetime.now(timezone.utc)


def stamp(when):
    return when.astimezone(timezone.utc).isoformat(timespec="microseconds")


def write(path, value):
    with path.open("xb") as f:
        f.write(encoded(value))


def digest_file(path):
    value = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def inside(root, relative):
    relative = Path(relative)
    path = root / relative
    require(not relative.is_absolute() and root in path.resolve().parents
            and path == path.resolve(), "invalid or redirected relative evidence path")
    return path


def file_pin(path, wanted):
    require(isinstance(wanted, str) and SHA256.fullmatch(wanted)
            and path.is_file() and not path.is_symlink()
            and digest_file(path) == wanted, f"file identity differs: {path.name}")
    return path


@contextmanager
def exclusive_launch(approval):
    runtime = REPO / ".runtime"
    runtime.mkdir(exist_ok=True)
    require(runtime.resolve() == runtime, "project runtime is redirected")
    allocation = {key: approval["host"][key] for key in ("machine", "gpu")}
    lock = runtime / ("p2-r-active-" + sha(encoded(allocation)))
    lock.mkdir()
    try:
        yield
    finally:
        lock.rmdir()


def manifest_files(root, skip=()):
    files = {}
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), "frozen tree contains a symbolic link")
        name = path.relative_to(root).as_posix()
        if name not in skip and not path.is_dir():
            require(path.is_file(), "frozen tree contains a nonregular file")
            files[name] = digest_file(path)
    return files


def host_fields(host):
    return isinstance(host, dict) and all(isinstance(host.get(key), str) and host[key].strip()
                                           for key in ("machine", "boot", "os", "gpu", "driver", "allocation"))


def approved(path, pin, phase, worklist, expected_commit, clock, historical=False):
    body = path.read_bytes()
    require(SHA256.fullmatch(pin) and sha(body) == pin, "trusted approval receipt SHA-256 differs")
    approval = json.loads(body)
    phases = approval["phases"]
    require(approval["schema"] == APPROVAL and approval["scope"] == "P2-R-department"
            and type(phases) is list and phase in phases and set(phases) <= set(PHASES),
            "approval does not allow this department phase")
    require(approval["reviewedDraftSha256"] == DEPARTMENT_DRAFT_SHA
            and approval["worklistSha256"] == sha(encoded(worklist)),
            "approval binds another proposal or worklist")
    for key in ("supervisorReply", "approvedPlan"):
        entry = approval[key]
        evidence = file_pin(inside(path.parent, entry["path"]), entry["sha256"])
        require(evidence.stat().st_size > 0, f"empty {key}")
    current = clock()
    sender = approval["supervisorReply"]["reviewedSender"]
    require(isinstance(sender, str) and sender.strip(), "missing operator-verified supervisor sender")
    reply_time = instant(approval["supervisorReply"]["receivedAt"])
    since, start, end = (instant(approval[key]) for key in ("logHistorySince", "notBefore", "notAfter"))
    require(since < start < end and reply_time <= start <= current
            and (historical or current < end), "reply or allocated time window does not permit launch")
    commit = approval["sourceCommit"]
    require(isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit)
            and commit == expected_commit, "approval source commit differs")
    require(host_fields(approval["host"]), "missing approved host, boot, driver, OS or GPU allocation")
    require(isinstance(approval["ollamaVersion"], str) and approval["ollamaVersion"].strip(),
            "missing approved Ollama version")
    endpoint = urlsplit(approval["ollamaUrl"])
    require(endpoint.scheme in ("http", "https") and endpoint.hostname
            and endpoint.username is None and endpoint.password is None and endpoint.port is not None
            and endpoint.path in ("", "/") and not endpoint.query and not endpoint.fragment,
            "Ollama URL must identify the approved service without credentials")
    build = approval["build"]
    build_root = inside(path.parent, build["directory"])
    require(build_root.is_dir() and manifest_files(build_root) == build["files"],
            "frozen build files differ")
    dlls = {}
    for key in ("rqcDll", "substrateDll"):
        dlls[key] = file_pin(inside(build_root, build[key]), build["files"][build[key]])
    for key in ("dotnet", "logCollector"):
        entry = approval[key]
        tool = Path(entry["path"])
        require(tool.is_absolute() and tool == tool.resolve() and os.access(tool, os.X_OK),
                f"{key} must name a resolved executable")
        dlls[key] = file_pin(tool, entry["sha256"])
    return approval, dlls


def same_qualification_identity(previous, current):
    same = (
        all(previous[key] == current[key] for key in ("sourceCommit", "worklistSha256", "ollamaUrl", "ollamaVersion"))
        and previous["approvedPlan"]["sha256"] == current["approvedPlan"]["sha256"]
        and previous["supervisorReply"]["reviewedSender"] == current["supervisorReply"]["reviewedSender"]
        and all(previous["host"][key] == current["host"][key] for key in ("machine", "boot", "os", "gpu", "driver"))
        and previous["dotnet"]["sha256"] == current["dotnet"]["sha256"]
        and all(previous["build"][key] == current["build"][key] for key in ("files", "rqcDll", "substrateDll"))
    )
    require(same, "regeneration host, plan, supervisor, service or build differs from qualification")


def log_snapshot(raw, since, until, host):
    value = json.loads(raw)
    require(value["schema"] == LOG_CAPTURE and value["host"] == host and host_fields(value["host"]),
            "log capture host, boot or allocation changed")
    require(instant(value["since"]) == since and instant(value["until"]) == until and since < until,
            "log capture queried the wrong interval")
    require(set(value["sources"]) == set(LOG_CLASSES), "system and GPU log sources are both required")
    for label, stream in value["sources"].items():
        require(stream["complete"] is True and instant(stream["readableFrom"]) <= since
                and instant(stream["readableUntil"]) >= until,
                f"{label}: log access or retained interval did not cover the query")
        require(isinstance(stream["sourceId"], str) and stream["sourceId"].strip()
                and isinstance(stream["querySha256"], str) and SHA256.fullmatch(stream["querySha256"]),
                f"{label}: missing log source or query identity")
        events = stream["events"]
        require(type(events) is list, f"{label}: missing event records")
        keys = set()
        for row in events:
            identity = row["id"]
            require(isinstance(identity, str) and identity and identity not in keys
                    and since <= instant(row["at"]) < until and isinstance(row["record"], str)
                    and row["record"].strip(), f"{label}: bad event identity, content or interval")
            keys.add(identity)
    return value


def audit_logs(before, after, since, cutoff, end, host):
    require(since < cutoff < end, "before/after observation boundaries are unordered")
    initial = log_snapshot(before, since, cutoff, host)
    final = log_snapshot(after, since, end, host)
    events = {}
    for name in LOG_CLASSES:
        left, right = initial["sources"][name], final["sources"][name]
        require(all(left[k] == right[k] for k in ("sourceId", "querySha256")),
                f"{name}: pre/post log source or query changed")
        historical = {row["id"]: row for row in right["events"] if instant(row["at"]) < cutoff}
        require(historical == {row["id"]: row for row in left["events"]},
                f"{name}: retained baseline changed during the observation")
        events[name] = [row["id"] for row in right["events"] if instant(row["at"]) >= cutoff]
    return {"status": "RELEVANT_EVENTS_RETAINED" if any(events.values()) else "NO_NEW_RELEVANT_EVENTS_IN_CAPTURE",
            "sourceCount": len(events), "eventIdsBySource": events,
            "since": stamp(since), "beforeUntil": stamp(cutoff), "afterUntil": stamp(end),
            "captureSha256": {"before": sha(before), "after": sha(after)}}


def audit_handoff(qualified, baseline):
    boundary = instant(qualified["until"])
    since, start = (instant(baseline[key]) for key in ("since", "until"))
    require(since <= boundary <= start, "regeneration baseline does not cover the qualification handoff")
    overlap = max(since, instant(qualified["since"]))
    for name in LOG_CLASSES:
        old, current = qualified["sources"][name], baseline["sources"][name]
        require(all(old[key] == current[key] for key in ("sourceId", "querySha256")),
                f"{name}: log source or query differs from qualification")
        prior = {row["id"]: row for row in old["events"] if instant(row["at"]) >= overlap}
        retained = {row["id"]: row for row in current["events"] if overlap <= instant(row["at"]) < boundary}
        require(prior == retained, f"{name}: overlapping qualification log records changed")
        require(not any(instant(row["at"]) >= boundary for row in current["events"]),
                f"{name}: relevant log event between qualification and regeneration")
    return {"status": "QUALIFICATION_HANDOFF_LOGS_COVERED", "qualifiedUntil": stamp(boundary),
            "regenerationBaselineUntil": stamp(start)}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class DepartmentRuntime:
    """Use the approved local collector and one allocated Ollama endpoint."""

    def __init__(self, approval, tools, clock=now):
        self.approval, self.tools, self.clock = approval, tools, clock
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def remaining(self, maximum=None):
        value = (instant(self.approval["notAfter"]) - self.clock()).total_seconds()
        require(value > 0, "approved window elapsed")
        return min(value, maximum) if maximum is not None else value

    def capture(self, bundle, label, since, until):
        path = bundle / f"logs-{label}.json"
        cmd = [str(self.tools["logCollector"]), "--since", stamp(since), "--until", stamp(until)]
        with path.open("xb") as output, (bundle / f"logs-{label}.stderr").open("xb") as errors:
            result = subprocess.run(cmd, cwd=REPO, stdout=output, stderr=errors, timeout=120)
        require(result.returncode == 0, f"{label}: log collector failed ({result.returncode})")
        return path.read_bytes()

    def api(self, route, data=None):
        request = Request(self.approval["ollamaUrl"].rstrip("/") + route,
                          data=None if data is None else encoded(data),
                          headers={"Content-Type": "application/json"})
        with self.opener.open(request, timeout=self.remaining(30)) as response:
            return json.load(response)

    def unloaded(self, model, digest, evidence):
        version = self.api("/api/version")["version"]
        matches = [item for item in self.api("/api/tags")["models"]
                   if item.get("name") == model or item.get("model") == model]
        require(version == self.approval["ollamaVersion"] and len(matches) == 1
                and matches[0]["digest"] == digest, "approved model digest or Ollama version missing")

        def loaded():
            return self.api("/api/ps")["models"]

        before = loaded()
        request = {"model": model, "keep_alive": 0, "stream": False}
        response = self.api("/api/generate", request) if resident(before, model, digest) else None
        deadline = time.monotonic() + self.remaining(30)
        after = loaded()
        while resident(after, model, digest) and time.monotonic() < deadline:
            time.sleep(min(0.5, self.remaining(0.5)))
            after = loaded()
        write(evidence, {"model": model, "digest": digest, "version": version,
                         "before": before, "unloadResponse": response, "after": after})
        verify_unload(evidence, model, digest, version)
        return version

    def run(self, argv, log):
        env = {name: value for name, value in os.environ.items()
               if name.lower() not in ("http_proxy", "https_proxy", "all_proxy",
                                       "dotnet_startup_hooks", "dotnet_additional_deps", "dotnet_shared_store")}
        env["AIJADE_GIT_COMMIT"] = self.approval["sourceCommit"]
        timeout = self.remaining()
        with log.open("xb") as out:
            return subprocess.run(argv, cwd=REPO, env=env, stdout=out,
                                  stderr=subprocess.STDOUT, timeout=timeout).returncode


def resident(rows, model, digest):
    require(type(rows) is list and all(isinstance(row, dict)
            and any(isinstance(row.get(key), str) and row[key] for key in ("model", "name"))
            for row in rows), "invalid Ollama model residency record")
    return any(row.get("digest") == digest or row.get("name") == model or row.get("model") == model for row in rows)


def verify_unload(path, model, digest, version):
    record = json.loads(path.read_bytes())
    require((record["model"], record["digest"], record["version"]) == (model, digest, version)
            and isinstance(version, str) and version.strip(), "unload evidence cites another service or model")
    before = resident(record["before"], model, digest)
    response = record["unloadResponse"]
    require((not before and response is None) or (before and isinstance(response, dict)
            and response.get("done") is True and response.get("done_reason") == "unload"),
            "a resident model was not acknowledged as unloaded")
    require(not resident(record["after"], model, digest), "approved model still resident after unload")


def arguments(template, bundle, approval, tools):
    resolved = {"{dotnet}": str(tools["dotnet"]), "{frozenRqcDll}": str(tools["rqcDll"]),
                "{frozenSubstrateDll}": str(tools["substrateDll"]),
                "{approvedOllamaUrl}": approval["ollamaUrl"]}
    return [str(inside(bundle, item[len("{bundleRoot}/"):])) if item.startswith("{bundleRoot}/")
            else resolved.get(item, item) for item in template]


def run_slot(bundle, item, group, phase, approval, tools, worklist_sha, runtime):
    folder = inside(bundle, item["directory"])
    folder.mkdir(parents=True, exist_ok=False)
    argv = arguments(item["argvTemplate"], bundle, approval, tools)
    write(folder / "launch-request.json", {"argv": argv, "requestedAt": stamp(runtime.clock())})
    version = runtime.unloaded(group["model"], group["historicalRun"]["modelDigest"], folder / "model-unload.log")
    require(version == approval["ollamaVersion"], "Ollama version differs from the approved setup")
    verify_unload(folder / "model-unload.log", group["model"], group["historicalRun"]["modelDigest"], version)
    unload = stamp(runtime.clock())
    start = stamp(runtime.clock())
    write(folder / "launch-start.json", {"startedAt": start})
    code = runtime.run(argv, folder / "runner.log")
    end = stamp(runtime.clock())
    files = read_inputs(inside(bundle, item["artifacts"]))
    for name in ("runner.log", "model-unload.log"):
        files[name] = (folder / name).read_bytes()
    record = {"schema": ("aijade.p2-r.qualification-launch.v1" if phase == "qualification"
                         else "aijade.p2-r.regeneration-launch.v1"),
              "index": item.get("index"), "group": group["id"], "worklistSha256": worklist_sha,
              "sourceCommit": approval["sourceCommit"], "runnerSha256": approval["build"]["files"][approval["build"]["rqcDll"]],
              "exitCode": code, "launchId": uuid4().hex, "unloadRecordedAt": unload,
              "startedAt": start, "finishedAt": end, "ollamaVersionAtStart": version,
              "fileSha256": {name: sha(raw) for name, raw in files.items() if raw is not None}}
    write(folder / "launch-receipt.json", record)
    require(code == 0, f"{group['id']}: runner exited {code}")
    require(all(raw is not None for raw in files.values())
            and not (inside(bundle, item["artifacts"]) / "incomplete-run.json").exists(),
            f"{group['id']}: incomplete run artifacts")
    summary = validate_summary(files["summary.json"])
    captured = group["historicalRun"]
    trials = 5 if phase == "qualification" else captured["config"]["trials"]
    require(summary["config"] == dict(captured["config"], trials=trials)
            and summary["sampling"]["modelDigest"] == captured["modelDigest"]
            and summary["sampling"]["ollamaVersion"] == version
            and summary["gitHash"] == approval["sourceCommit"]
            and summary["sampling"].get("warmUp") is True and "resumed" not in summary
            and summary["nExecutions"] == item["steps"], f"{group['id']}: fresh run identity differs")
    if phase == "regeneration":
        result = compare_inputs(read_inputs(REPO / captured["directory"]), files)
        require(result["complete"], f"{group['id']}: regeneration records are incomplete")
        write(folder / "archive-comparison.json", result)
    return record


def proven_qualification(bundle, qualification_pin, approval_pin, approval, worklist):
    body = file_pin(bundle / "phase-result.json", qualification_pin).read_bytes()
    report = json.loads(body)
    require(report["schema"] == PHASE_RECEIPT and report["phase"] == "qualification"
            and report["status"] == "QUALIFICATION_EVIDENCE_COMPLETE"
            and report["approvalSha256"] == approval_pin
            and report["files"] == manifest_files(bundle, ("phase-result.json",)),
            "qualification receipt or bound files do not match")
    start, end = (instant(report[key]) for key in ("observationStartedAt", "observationFinishedAt"))
    require(instant(approval["notBefore"]) <= start < end <= min(instant(approval["notAfter"]), now()),
            "qualification observation falls outside the approved window")
    since = instant(approval["logHistorySince"])
    after = (bundle / "logs-after.json").read_bytes()
    log = audit_logs((bundle / "logs-before.json").read_bytes(), after, since, start, end, approval["host"])
    repeats = audit(bundle, worklist)
    require(log["status"] == "NO_NEW_RELEVANT_EVENTS_IN_CAPTURE"
            and repeats["status"] == "CAPTURED_REPEATS_MATCH" and repeats["positiveControlDiscriminationRecorded"],
            "qualification re-audit failed")
    require(repeats["observedServerVersions"] == [approval["ollamaVersion"]],
            "qualification used another Ollama version")
    version = approval["ollamaVersion"]
    for group in worklist["groups"]:
        for item in group["qualification"]:
            directory = inside(bundle, item["directory"])
            row = json.loads((directory / "launch-receipt.json").read_bytes())
            require(start <= instant(row["unloadRecordedAt"]) < instant(row["startedAt"])
                    < instant(row["finishedAt"]) <= end, "launch falls outside the log coverage window")
            verify_unload(directory / "model-unload.log", group["model"],
                          group["historicalRun"]["modelDigest"], version)
    return {"sha256": sha(body), "finalLogs": log_snapshot(after, since, end, approval["host"])}


def perform(phase, bundle, approval, approval_pin, tools, worklist, runtime, qualification=None):
    if phase == "regeneration":
        require(isinstance(qualification, dict) and SHA256.fullmatch(qualification.get("sha256", "")),
                "regeneration requires an audited qualification receipt")
    bundle.mkdir(exist_ok=False)
    worklist_sha = sha(encoded(worklist))
    write(bundle / "runner-identity.json", {"schema": "aijade.p2-r.runner-identity.v1",
          "worklistSha256": worklist_sha, "sourceCommit": approval["sourceCommit"],
          "runnerSha256": approval["build"]["files"][approval["build"]["rqcDll"]]})
    start, since = runtime.clock(), instant(approval["logHistorySince"])
    report = {"schema": PHASE_RECEIPT, "phase": phase, "approvalSha256": approval_pin,
              "worklistSha256": worklist_sha, "observationStartedAt": stamp(start),
              "qualificationReceiptSha256": qualification["sha256"] if qualification else None,
              "status": "INCOMPLETE_DEPARTMENT_EVIDENCE", "launchesStarted": 0}
    before = None
    error = None
    try:
        before = runtime.capture(bundle, "before", since, start)
        baseline = log_snapshot(before, since, start, approval["host"])
        if qualification is not None:
            report["qualificationHandoff"] = audit_handoff(qualification["finalLogs"], baseline)
        for group in worklist["groups"]:
            slots = group["qualification"] if phase == "qualification" else [group["regeneration"]]
            for item in slots:
                run_slot(bundle, item, group, phase, approval, tools, worklist_sha, runtime)
        if phase == "qualification":
            for control in worklist["positiveControls"]:
                path = inside(bundle, control["artifacts"])
                path.parent.mkdir(parents=True, exist_ok=True)
                argv = arguments(control["argvTemplate"], bundle, approval, tools)
                write(path.with_suffix(".request.json"), {"argv": argv, "requestedAt": stamp(runtime.clock())})
                code = runtime.run(argv, path.with_suffix(".log"))
                require(code == 0, "open sampling control failed")
            repeats = audit(bundle, worklist)
            write(bundle / "repeat-audit.json", repeats)
            require(repeats["status"] == "CAPTURED_REPEATS_MATCH"
                    and repeats["positiveControlDiscriminationRecorded"], "repeat or open-control evidence did not match")
    except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError, KeyboardInterrupt) as exc:
        error = str(exc) or type(exc).__name__
    end = runtime.clock()
    report["observationFinishedAt"] = stamp(end)
    report["launchesStarted"] = sum(1 for _ in bundle.rglob("launch-start.json"))
    try:
        after = runtime.capture(bundle, "after", since, end)
        if before is not None:
            report["logs"] = audit_logs(before, after, since, start, end, approval["host"])
    except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError, KeyboardInterrupt) as exc:
        report["logError"] = str(exc) or type(exc).__name__
    report["error"] = error
    if error is None and end <= instant(approval["notAfter"]):
        status = report.get("logs", {}).get("status")
        if status == "RELEVANT_EVENTS_RETAINED":
            report["status"] = "DEPARTMENT_PHASE_REQUIRES_INVESTIGATION"
        elif status == "NO_NEW_RELEVANT_EVENTS_IN_CAPTURE":
            report["status"] = ("QUALIFICATION_EVIDENCE_COMPLETE" if phase == "qualification"
                                else "REGENERATION_EVIDENCE_COMPLETE")
    report["files"] = manifest_files(bundle)
    write(bundle / "phase-result.json", report)
    return report


def plan(worklist):
    return {"schema": "aijade.p2-r.department-launch-plan.v1", "status": "OFFLINE_COMMAND_PLAN",
            "worklistSha256": sha(encoded(worklist)), "formalRunsStarted": 0, "qualification": "NOT_RUN",
            "regeneration": "NOT_RUN", "groups": worklist["groups"],
            "positiveControls": worklist["positiveControls"],
            "logCaptureSchema": LOG_CAPTURE, "replyReceiptSchema": APPROVAL}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    commands.add_parser("plan", help="render the fixed worklist without executing processes")
    logs = commands.add_parser("audit-logs", help="compare saved captures without talking to their collector")
    logs.add_argument("--before", type=Path, required=True)
    logs.add_argument("--after", type=Path, required=True)
    run = commands.add_parser("run", help="execute exactly one phase after the reviewed reply")
    run.add_argument("phase", choices=PHASES)
    run.add_argument("--approval", type=Path, required=True)
    run.add_argument("--approval-sha256", required=True, help="SHA-256 of the locally verified approval receipt")
    run.add_argument("--bundle", type=Path, required=True)
    run.add_argument("--qualification-bundle", type=Path)
    run.add_argument("--qualification-receipt-sha256", help="operator-verified complete qualification receipt")
    run.add_argument("--qualification-approval", type=Path, help="original approval if the allocation window changed")
    run.add_argument("--qualification-approval-sha256", help="trusted SHA-256 of the original qualification approval")
    args = parser.parse_args()
    try:
        if args.mode == "audit-logs":
            before, after = args.before.read_bytes(), args.after.read_bytes()
            left, right = json.loads(before), json.loads(after)
            result = audit_logs(before, after, instant(left["since"]), instant(left["until"]),
                                instant(right["until"]), left["host"])
            sys.stdout.buffer.write(encoded(result))
            return int(result["status"] != "NO_NEW_RELEVANT_EVENTS_IN_CAPTURE")
        worklist = prepare()
        if args.mode == "plan":
            sys.stdout.buffer.write(encoded(plan(worklist)))
            return 0
        approval_path = args.approval.resolve(strict=True)
        bundle = args.bundle.absolute()
        require(bundle.resolve() == bundle and bundle.parent.is_dir() and not bundle.exists()
                and bundle.is_relative_to(REPO.parent)
                and (not bundle.is_relative_to(REPO) or bundle.is_relative_to(REPO / ".runtime")),
                "choose a new AIJADE-local bundle outside the source checkout or under its ignored .runtime")
        require(approval_path.is_relative_to(REPO.parent), "approval evidence must stay in the AIJADE workspace")
        head = subprocess.check_output(["git", "-C", REPO, "rev-parse", "HEAD"], text=True).strip()
        changes = subprocess.check_output(["git", "-C", REPO, "status", "--porcelain=v1", "--untracked-files=all",
                                           "--ignore-submodules=none"])
        require(not changes, "the complete source checkout must be clean")
        approval, tools = approved(approval_path, args.approval_sha256, args.phase, worklist, head, now)
        qualification = None
        if args.phase == "regeneration":
            require(args.qualification_bundle is not None and args.qualification_receipt_sha256
                    and args.qualification_bundle.resolve().is_relative_to(REPO.parent),
                    "regeneration requires the previously captured AIJADE-local qualification bundle")
            require(bool(args.qualification_approval) == bool(args.qualification_approval_sha256),
                    "the original qualification approval and its trusted SHA-256 are a pair")
            qualification_approval_path = (args.qualification_approval.resolve(strict=True)
                                           if args.qualification_approval else approval_path)
            require(qualification_approval_path.is_relative_to(REPO.parent),
                    "qualification approval must stay in the AIJADE workspace")
            qualification_approval_pin = args.qualification_approval_sha256 or args.approval_sha256
            prior, _ = approved(qualification_approval_path, qualification_approval_pin, "qualification",
                                worklist, head, now, historical=True)
            same_qualification_identity(prior, approval)
            qualification = proven_qualification(args.qualification_bundle.resolve(), args.qualification_receipt_sha256,
                                                 qualification_approval_pin, prior, worklist)
        else:
            require(not any((args.qualification_bundle, args.qualification_receipt_sha256,
                             args.qualification_approval, args.qualification_approval_sha256)),
                    "qualification starts in a fresh bundle")
        with exclusive_launch(approval):
            report = perform(args.phase, bundle, approval, args.approval_sha256, tools, worklist,
                             DepartmentRuntime(approval, tools), qualification)
        sys.stdout.buffer.write(encoded({"status": report["status"], "phase": args.phase,
                                         "launchesStarted": report["launchesStarted"],
                                         "receiptSha256": digest_file(bundle / "phase-result.json")}))
        return 0 if report["status"] in ("QUALIFICATION_EVIDENCE_COMPLETE", "REGENERATION_EVIDENCE_COMPLETE") else 1
    except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
