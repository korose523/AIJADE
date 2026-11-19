#!/usr/bin/env python3
"""Prepare P2-R from retained evidence and audit captured repeats without launching anything."""

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

from regen_compare_v2 import CONDITIONS, INPUT_NAMES, SHA256, compare_inputs, read_inputs, validate_summary


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PLAN = REPO / "experiments/plans/2026-11-04-p2-r-regeneration.md"
PLAN_SHA = "a0e2af9d49189718575bef39dce8cd7fda4127cee03e077311c3af1ba6e69731"
DEPARTMENT_DRAFT_SHA = "d84379d92733ece1e57f41198433cf39ecbeb731379d01ebcb1f3b15b9ba0778"
ARCHIVE_RUN = "rq-c-s42-ollama-t30-r5"
QUALIFICATION_RUN = "rq-c-s42-ollama-t5-r5"
REPEATS = 5
TRIALS = 5
ARCHIVES = {
    "second-family": (
        "family-gpu", "llama3.1:8b", "A",
        "56e40a5e54d6a3bbe2884d25bf5e6049d2dd4ecb5c338a177764d709766b4121",
        "9f53d82b6e38ff5286fc62c062cc54579d7a6e8fa9a1b1232f84bea486ce4d61",
        "f8af63325d4df62c12c0c5e44ac5c565bc5293f0ac75cbf6e49b9baf1e9554f0",
    ),
    "template-a": (
        "template-gpu/A", "qwen2.5-coder:7b-instruct", "A",
        "73dfd090ff3410f1a24e62ff75ab69b0bab90a01fbedfe502ad285f7b6b18436",
        "928a99838f7b57696c2e7fe4731bc3b2890b16c2ed7ef9461d1ad3dae61d2ae3",
        "15465c00d2ecb8427274baef4be559bf6ef27792ff2051c77159154e4cf6ef0e",
    ),
    "template-b": (
        "template-gpu/B", "qwen2.5-coder:7b-instruct", "B",
        "fc76a3cc69ed351108052c68772902a03b936aa728c28542a0de3ad74c7b07c0",
        "fd4b5408eb2592a9322728e23b51ad669f82bbdcdc8d7b5365636a3ef9439be2",
        "474fe98434ff6d24111829bc80df83825192616e57cd8f9f01f341f62e5cd894",
    ),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(document):
    return (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def runner_argv(config, trials, subdir):
    return [
        "{dotnet}", "{frozenRqcDll}", "--backend", config["backend"], "--model", config["model"],
        "--trials", str(trials), "--rounds", str(config["rounds"]), "--tasks", str(config["tasks"]),
        "--seed", str(config["seed"]), "--p-correct", str(config["pCorrect"]),
        "--prune-threshold", str(config["pruneThreshold"]), "--min-calls", str(config["pruneMinCalls"]),
        "--temperature", "0", "--timeout-ms", "3600000", "--max-reply-tokens", str(config["maxReplyTokens"]),
        "--num-ctx", str(config["numCtx"]), "--verify-template", config.get("verifyTemplate", "A"),
        "--ollama-base-url", "{approvedOllamaUrl}", "--out", "{bundleRoot}/" + subdir, "--save-candidates",
    ]


def prepare():
    """Return a byte-repeatable draft worklist bound to the archived inputs."""
    require(sha(PLAN.read_bytes()) == PLAN_SHA, "public P2-R protocol bytes differ")
    groups = []
    for group, (folder, model, template, *hashes) in ARCHIVES.items():
        directory = HERE / folder / ARCHIVE_RUN
        inputs = read_inputs(directory)
        require(all(inputs[name] is not None and sha(inputs[name]) == digest
                    for name, digest in zip(INPUT_NAMES, hashes)), f"{group}: pinned archive bytes differ")
        summary = validate_summary(inputs["summary.json"])
        config, sample = summary["config"], summary["sampling"]
        require(config["model"] == model and config.get("verifyTemplate", "A") == template
                and (config["trials"], config["rounds"], config["tasks"], config["seed"]) == (30, 5, 12, 42)
                and (config["numCtx"], config["maxReplyTokens"], sample["seed"], sample["temperature"])
                == (4096, 4096, 3759066737, 0)
                and sample.get("warmUp") is True, f"{group}: archived protocol settings differ")
        replay = compare_inputs(inputs, inputs)
        require(replay["identical"], f"{group}: retained aligned archive is incomplete")

        qualifications = []
        for index in range(1, REPEATS + 1):
            prefix = f"qualification/{group}/pass-{index:02}"
            qualifications.append({
                "index": index,
                "directory": prefix,
                "artifacts": prefix + "/" + QUALIFICATION_RUN,
                "argvTemplate": runner_argv(config, TRIALS, prefix),
                "steps": TRIALS * config["rounds"] * config["tasks"] * len(CONDITIONS),
            })
        prefix = f"regeneration/{group}"
        groups.append({
            "id": group,
            "model": model,
            "verifierTemplate": template,
            "historicalRun": {
                "directory": directory.relative_to(REPO).as_posix(),
                "fileSha256": dict(zip(INPUT_NAMES, hashes)),
                "config": config,
                "modelDigest": sample["modelDigest"],
                "steps": sum(report["sharedSteps"] for report in replay["conditions"].values()),
            },
            "qualification": qualifications,
            "regeneration": {
                "directory": prefix,
                "artifacts": prefix + "/" + ARCHIVE_RUN,
                "argvTemplate": runner_argv(config, config["trials"], prefix),
                "steps": summary["nExecutions"],
            },
        })
    modeled = {group["model"]: group["historicalRun"]["modelDigest"] for group in groups}
    return {
        "schema": "aijade.p2-r.department-worklist.v1",
        "status": "OFFLINE_PREPARATION_ONLY",
        "historicalPlan": {"path": PLAN.relative_to(REPO).as_posix(), "sha256": PLAN_SHA},
        "departmentPlanDraftSha256": DEPARTMENT_DRAFT_SHA,
        "collaborationStatus": "AWAITING_SUPERVISOR_REPLY_AND_DEPARTMENT_HOST",
        "groups": groups,
        "positiveControls": [
            {
                "model": model,
                "modelDigest": digest,
                "argvTemplate": [
                    "{dotnet}", "{frozenSubstrateDll}", "verify", "--model", model, "--runs", "5",
                    "--seed-strategy", "fixed", "--control", "--base-url", "{approvedOllamaUrl}",
                    "--out", f"{{bundleRoot}}/qualification/controls/control-{index}.json",
                ],
                "artifacts": f"qualification/controls/control-{index}.json",
                "openedSampling": {"temperature": 1, "top_k": 40, "top_p": 0.95},
            }
            for index, (model, digest) in enumerate(modeled.items(), 1)
        ],
        "hostEvidence": [
            "Supervisor response and agreed execution-plan identity.",
            "Assigned account access, GPU allocation and approved observation window.",
            "Hardware, driver, OS, model service, runner, build and model identities.",
            "Pre-check error-log query, retained interval and visibility for system and GPU errors.",
            "Comparable post-check error exports covering qualification and regeneration windows.",
        ],
        "qualifyingToolDoesNotLaunch": True,
        "formalRunsStarted": 0,
    }


def contained(root, relative):
    path = root / relative
    require(root in path.resolve().parents and path.resolve() == path.absolute(),
            f"{relative}: redirected bundle path")
    return path


def instant(value):
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(timestamp.utcoffset() is not None, "a launch timestamp must include its time zone")
    return timestamp


def read_pass(bundle, item, group, identity, worklist_sha):
    """Check stored identities and capture completeness. The receipt is an operator record."""
    prefix = item["directory"]
    receipt_bytes = contained(bundle, prefix + "/launch-receipt.json").read_bytes()
    record = json.loads(receipt_bytes)
    require(record["schema"] == "aijade.p2-r.qualification-launch.v1", "unsupported launch receipt")
    require((record["group"], record["index"], record["worklistSha256"]) ==
            (group["id"], item["index"], worklist_sha) and type(record["index"]) is int,
            "launch receipt cites the wrong slot or worklist")
    require((record["sourceCommit"], record["runnerSha256"]) ==
            (identity["sourceCommit"], identity["runnerSha256"]), "launch source or runner differs")
    require(type(record["exitCode"]) is int and record["exitCode"] == 0, "runner did not exit successfully")
    launch_id = record["launchId"]
    require(isinstance(launch_id, str) and launch_id.strip(), "missing independent launch identity")
    unload, start, end = (instant(record[key]) for key in ("unloadRecordedAt", "startedAt", "finishedAt"))
    require(unload < start < end, "unload and launch records are out of order")

    output_dir = contained(bundle, item["artifacts"])
    require(not (output_dir / "incomplete-run.json").exists(), "retained incomplete runner marker")
    inputs = {name: contained(bundle, item["artifacts"] + "/" + name).read_bytes() for name in INPUT_NAMES}
    logs = {name: contained(bundle, prefix + "/" + name).read_bytes() for name in ("runner.log", "model-unload.log")}
    require(all(log.strip() for log in logs.values()), "missing runner or model-unload evidence")
    require(b"[warm-up] model loaded; first-request output discarded" in logs["runner.log"]
            and b"[resume]" not in logs["runner.log"], "expected fresh warm-up with no resume")
    bindings = {name: sha(raw) for name, raw in {**inputs, **logs}.items()}
    require(bindings == record["fileSha256"], "launch files differ from their recorded hashes")
    summary = validate_summary(inputs["summary.json"])
    expected = group["historicalRun"]
    require(summary["config"] == dict(expected["config"], trials=TRIALS)
            and summary["sampling"]["modelDigest"] == expected["modelDigest"],
            "captured settings differ from the archived configuration")
    require(summary["sampling"].get("warmUp") is True and "resumed" not in summary
            and summary.get("gitHash") == identity["sourceCommit"], "runner summary does not describe a fresh frozen run")
    checked = compare_inputs(inputs, inputs)
    require(checked["identical"] and summary["nExecutions"] == item["steps"],
            "qualification records are not complete")
    server = summary["sampling"].get("ollamaVersion")
    require(isinstance(server, str) and server.strip(), "missing Ollama version from the launch")
    return {
        "inputs": inputs,
        "hashes": bindings,
        "receiptSha256": sha(receipt_bytes),
        "launchId": launch_id,
        "interval": (unload, end),
        "serverVersion": server,
    }


def check_control(bundle, control, server_versions):
    body = contained(bundle, control["artifacts"]).read_bytes()
    record = json.loads(body)
    require(record["model"] == control["model"] and record["digest"] == control["modelDigest"],
            "control model identity differs")
    require(record["serverVersion"] in server_versions, "control server does not match recorded launches")
    opened = record["control"]
    require(record["check"]["seedStrategy"] == "fixed" and record["check"]["runs"] == 5
            and opened["runs"] == 5 and len(opened["perRun"]) == 5,
            "wrong control strategy or population")
    require(all(opened["sampling"].get(key) == value for key, value in control["openedSampling"].items()),
            "positive-control sampling settings differ")
    hashes = [entry["hash"] for entry in opened["perRun"]]
    require(all(isinstance(item, str) and item for item in hashes)
            and [entry["index"] for entry in opened["perRun"]] == list(range(5))
            and len(set(hashes)) == opened["uniqueOutputs"],
            "recorded control output multiplicity is inconsistent")
    return {
        "model": control["model"], "fileSha256": sha(body),
        "openedDistinctOutputs": len(set(hashes)),
        "discriminative": opened["verdict"] == "divergent" and len(set(hashes)) > 1
        and record["verdict"] == "pass" and record["discriminative"] is True,
    }


def audit(bundle, worklist):
    bundle = bundle.resolve()
    identity_bytes = contained(bundle, "runner-identity.json").read_bytes()
    identity = json.loads(identity_bytes)
    source_commit = identity["sourceCommit"]
    runner_sha = identity["runnerSha256"]
    worklist_sha = sha(encoded(worklist))
    require(identity["schema"] == "aijade.p2-r.runner-identity.v1"
            and identity["worklistSha256"] == worklist_sha,
            "runner identity cites another worklist")
    require(isinstance(source_commit, str) and len(source_commit) == 40
            and all(char in "0123456789abcdef" for char in source_commit)
            and isinstance(runner_sha, str) and SHA256.fullmatch(runner_sha),
            "runner identity lacks commit or executable digest")
    issues, groups, controls = [], [], []
    launch_ids, intervals, server_versions = set(), [], set()
    for group in worklist["groups"]:
        slots = []
        for item in group["qualification"]:
            try:
                row = read_pass(bundle, item, group, identity, worklist_sha)
                require(row["launchId"] not in launch_ids, "an independent launch was already counted")
                launch_ids.add(row["launchId"])
                intervals.append(row["interval"])
                server_versions.add(row["serverVersion"])
                slots.append((item["index"], row))
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                issues.append({"directory": item["directory"], "reason": str(exc)})
        compared = []
        if slots and slots[0][0] == 1:
            for index, row in slots[1:]:
                result = compare_inputs(slots[0][1]["inputs"], row["inputs"])
                compared.append({
                    "pass": index,
                    "status": result["status"],
                    "conditions": {
                        key: {
                            "identicalPrefixSteps": value["identicalPrefixSteps"],
                            "firstDivergence": None if value["firstDivergence"] is None else {
                                item: value["firstDivergence"][item] for item in ("step", "skill", "differs")
                            },
                        }
                        for key, value in result["conditions"].items()
                    },
                })
        groups.append({
            "id": group["id"],
            "completePasses": [{"index": index, "receiptSha256": row["receiptSha256"], "fileSha256": row["hashes"]}
                               for index, row in slots],
            "comparisonsAgainstPassOne": compared,
        })
    if len(server_versions) > 1:
        issues.append({"reason": "Ollama version changed across captured qualification launches"})
    ordered = sorted(intervals)
    if any(current[0] < previous[1] for previous, current in zip(ordered, ordered[1:])):
        issues.append({"reason": "recorded launch intervals overlap"})
    for control in worklist["positiveControls"]:
        try:
            controls.append(check_control(bundle, control, server_versions))
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            issues.append({"directory": control["artifacts"], "reason": str(exc)})
    complete = all(len(group["completePasses"]) == REPEATS for group in groups) and not issues
    parity = complete and all(row["status"] == "IDENTICAL"
                              for group in groups for row in group["comparisonsAgainstPassOne"])
    return {
        "schema": "aijade.p2-r.qualification-record-audit.v1",
        "worklistSha256": worklist_sha,
        "runnerIdentitySha256": sha(identity_bytes),
        "status": "INCOMPLETE_RECORD" if not complete else "CAPTURED_REPEATS_MATCH" if parity else "CAPTURED_REPEATS_DIFFER",
        "groups": groups,
        "positiveControls": controls,
        "positiveControlDiscriminationRecorded": len(controls) == len(worklist["positiveControls"])
        and all(control["discriminative"] for control in controls),
        "observedServerVersions": sorted(server_versions),
        "issues": issues,
        "formalQualificationDetermined": False,
        "hardwareLogsReviewed": False,
        "formalRunsStartedByAudit": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-bundle", type=Path, help="read-only audit of a copied qualification bundle")
    args = parser.parse_args()
    try:
        worklist = prepare()
        report = worklist if args.audit_bundle is None else audit(args.audit_bundle, worklist)
        sys.stdout.buffer.write(encoded(report))
        if report["status"] == "INCOMPLETE_RECORD":
            return 2
        if args.audit_bundle is not None and (
            report["status"] == "CAPTURED_REPEATS_DIFFER" or not report["positiveControlDiscriminationRecorded"]
        ):
            return 1
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
