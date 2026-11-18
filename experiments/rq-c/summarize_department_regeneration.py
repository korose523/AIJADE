#!/usr/bin/env python3
"""Recompute the recorded-label comparison for complete P2-R department captures."""

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import sys

from launch_department_regeneration import PHASE_RECEIPT, file_pin, inside, manifest_files
from oracle_audit import diagnostics
from prepare_department_regeneration import HERE, REPO, encoded, instant, prepare, require, sha
from regen_compare_v2 import CONDITIONS, INPUT_NAMES, SHA256, compare_inputs, load_rows, read_inputs, validate_summary


MODEL_PINS = {
    "p2-models.json": "9af0afb92933ce53fcd311328724393822a3b878d2986fb9cc4626726fd7ae21",
    "oracle-audit.json": "615f08d8fc849c3acfbbf7c6662efc5a08e3733d074032de2c8282315e9fffae",
}
ARCHIVED_LABELS = {
    "second-family": ("second family (llama3.1:8b)", "fam"),
    "template-a": ("prompt template A (7B, GPU host)", "tplA"),
    "template-b": ("prompt template B (7B, GPU host)", "tplB"),
}
RATES = ("hallucinationRate", "missRate", "agreement", "falseDiscoveryRate", "falseOmissionRate")


@dataclass
class Skill:
    identity: tuple
    calls: int = 0
    successes: int = 0
    last_execution_ok: bool = False


def summarize_records(inputs):
    summary = validate_summary(inputs["summary.json"])
    config = summary["config"]
    rows = load_rows(inputs, config["rounds"], config["tasks"])
    per_cell = config["trials"] * config["rounds"] * config["tasks"]
    require(all(len(records) == per_cell for records in rows.values()), "recorded population is incomplete")
    skills = {}
    cells = {condition: {"success": 0, "failure": 0} for condition in CONDITIONS}
    for condition, records in rows.items():
        for trial, candidate in records:
            key = trial["skillId"]
            identity = (condition, trial["trial"], trial["taskId"], trial["selfVerdict"], candidate["code"])
            skill = skills.get(key)
            require(trial["reused"] is (skill is not None), "skill reuse does not match generation order")
            if skill is None:
                skill = Skill(identity)
                skills[key] = skill
            require(skill.identity == identity, "recorded identity, verdict or code changed within a skill")
            skill.calls += 1
            skill.successes += trial["execOk"]
            skill.last_execution_ok = trial["execOk"]

    require(type(summary["nSkills"]) is int and summary["nSkills"] == len(skills)
            and type(summary["nExecutions"]) is int and summary["nExecutions"] == per_cell * len(CONDITIONS),
            "reported skill or execution denominator differs")
    judged, distinct = [], {}
    for skill in skills.values():
        cell, _, task, verdict, code = skill.identity
        outcome = "success" if 2 * skill.successes >= skill.calls else "failure"
        cells[cell][outcome] += 1
        if verdict is not None:
            row = (task, verdict == "pass", skill.last_execution_ok)
            judged.append(row)
            distinct.setdefault((task, code), row)

    unusable = [row for row in distinct.values() if not row[2]]
    false_passes = [row for row in unusable if row[1]]
    return {
        "executions": sum(map(len, rows.values())),
        "skills": len(skills),
        "tasks": len({skill.identity[2] for skill in skills.values()}),
        "cells": cells,
        "diagnostics": diagnostics(judged),
        "distinctJudgedCandidates": {
            "candidates": len(distinct), "unusable": len(unusable),
            "unusableTasks": len({row[0] for row in unusable}), "falsePasses": len(false_passes),
            "falsePassTasks": len({row[0] for row in false_passes}),
        },
    }


def canonical_archives():
    models, oracle = (json.loads(file_pin(HERE / name, pin).read_bytes()) for name, pin in MODEL_PINS.items())
    distinct = {record["slug"]: record["labels"]["asRun"]["distinct"] for record in oracle["runs"]}
    return models, distinct


def measurements_match(actual, expected):
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(measurements_match(a, b) for a, b in zip(actual, expected))
    if type(actual) in (int, float) and type(expected) in (int, float):
        return math.isclose(actual, expected, rel_tol=0, abs_tol=1e-10)
    return actual == expected


def verify_archived_tally(group, tally, references):
    models, distinct = references
    label, slug = ARCHIVED_LABELS[group["id"]]
    expected = models[label]
    require(expected["run"] == group["historicalRun"]["directory"]
            and tally["skills"] == expected["nSkills"] and tally["tasks"] == expected["nTasks"]
            and tally["cells"] == expected["cells"] and tally["distinctJudgedCandidates"] == distinct[slug],
            f"{group['id']}: recorded skill or candidate counts differ from pinned analyses")
    lhs = tally["diagnostics"]
    rhs = expected["diagnostics"]
    scalar_fields = ("n", "tasks", "confusion", "usableShare")
    require(all(measurements_match(lhs[key], rhs[key]) for key in scalar_fields),
            f"{group['id']}: verifier denominators differ from the pinned analysis")
    for name in (*RATES, "missMinusHallucination"):
        require(name in lhs and name in rhs and set(lhs[name]) == set(rhs[name])
                and all(measurements_match(lhs[name][key], rhs[name][key]) for key in lhs[name]),
                f"{group['id']}: recorded {name} differs from the pinned analysis")


def verified_phase(bundle, pin, worklist):
    body = file_pin(bundle / "phase-result.json", pin).read_bytes()
    report = json.loads(body)
    worklist_sha = sha(encoded(worklist))
    require(
        report["schema"] == PHASE_RECEIPT and report["phase"] == "regeneration"
        and report["status"] == "REGENERATION_EVIDENCE_COMPLETE"
        and report["worklistSha256"] == worklist_sha and report["error"] is None
        and report["launchesStarted"] == len(worklist["groups"])
        and report["logs"]["status"] == "NO_NEW_RELEVANT_EVENTS_IN_CAPTURE"
        and report["qualificationHandoff"]["status"] == "QUALIFICATION_HANDOFF_LOGS_COVERED"
        and all(isinstance(report[key], str) and SHA256.fullmatch(report[key])
                for key in ("approvalSha256", "qualificationReceiptSha256")),
        "pinned phase receipt does not describe a completed regeneration",
    )
    require(report["files"] == manifest_files(bundle, ("phase-result.json",)), "regeneration bundle files differ")
    identity = json.loads(inside(bundle, "runner-identity.json").read_bytes())
    require(identity["schema"] == "aijade.p2-r.runner-identity.v1" and identity["worklistSha256"] == worklist_sha
            and re.fullmatch("[0-9a-f]{40}", identity["sourceCommit"])
            and SHA256.fullmatch(identity["runnerSha256"]), "regeneration runner identity is incomplete")
    require(instant(report["observationStartedAt"]) < instant(report["observationFinishedAt"]),
            "regeneration observation window is incomplete")
    return report, identity


def report_bindings(inputs, archived_hashes=None):
    require(all(inputs[name] is not None for name in INPUT_NAMES), "missing complete three-file capture")
    actual = {name: sha(raw) for name, raw in inputs.items()}
    require(archived_hashes is None or actual == archived_hashes, "archived capture changed")
    return actual


def capture_comparison(group, archived, bundle, phase, identity):
    spec = group["regeneration"]
    out = inside(bundle, spec["artifacts"])
    candidate = read_inputs(out)
    hashes = report_bindings(candidate)
    receipt_dir = inside(bundle, spec["directory"])
    record = json.loads((receipt_dir / "launch-receipt.json").read_bytes())
    scope = ("sourceCommit", "runnerSha256", "worklistSha256")
    require(record["schema"] == "aijade.p2-r.regeneration-launch.v1"
            and record["group"] == group["id"] and type(record["exitCode"]) is int and record["exitCode"] == 0
            and all(record[key] == identity[key] for key in scope)
            and record["fileSha256"] == {**hashes, **{
                name: sha((receipt_dir / name).read_bytes()) for name in ("runner.log", "model-unload.log")
            }}
            and not (out / "incomplete-run.json").exists(), f"{group['id']}: launch does not bind its completed artifacts")
    start, end = (instant(phase[key]) for key in ("observationStartedAt", "observationFinishedAt"))
    unload, launched, finished = (instant(record[key]) for key in ("unloadRecordedAt", "startedAt", "finishedAt"))
    summary = validate_summary(candidate["summary.json"])
    require(start <= unload < launched < finished <= end
            and summary["gitHash"] == identity["sourceCommit"] and summary["nExecutions"] == spec["steps"]
            and summary["sampling"]["warmUp"] is True and "resumed" not in summary
            and summary["sampling"]["ollamaVersion"] == record["ollamaVersionAtStart"],
            f"{group['id']}: launch, source or timing falls outside the recorded phase")
    comparison = compare_inputs(archived, candidate)
    require(comparison["complete"] and comparison["scope"] == "FULL_RUN"
            and comparison == json.loads((receipt_dir / "archive-comparison.json").read_bytes()),
            f"{group['id']}: retained comparator output does not match the complete inputs")
    return candidate, hashes, comparison, (unload, finished)


def public_alignment(comparison):
    result = {}
    for name, cell in comparison["conditions"].items():
        safe = dict(cell)
        first = cell["firstDivergence"]
        if first is not None:
            safe["firstDivergence"] = {key: first[key] for key in ("step", "skill", "differs")}
        result[name] = safe
    return {"status": comparison["status"], "conditions": result}


def report(worklist, bundle=None, pin=None):
    references = canonical_archives()
    result = {
        "schema": "aijade.p2-r.department-paired-statistics.v1",
        "scope": "RETAINED_ARCHIVE_SELF_CHECK" if bundle is None else "RECORDED_REGENERATION_COMPARISON",
        "worklistSha256": sha(encoded(worklist)),
        "referenceAnalysisSha256": MODEL_PINS,
        "regenerationPhaseReceiptSha256": pin,
        "formalRunsStartedByReport": 0,
        "exploratoryOracleRetally": "NOT_RUN_BY_THIS_REPORT",
        "method": {
            "analysisUnit": "skill, after all recorded calls",
            "verifierTruth": "final recorded execution, among judged skills",
            "cellUsability": "at least half of recorded calls succeeded",
            "candidateUnit": "first judged skill for each task and exact code",
            "bootstrap": "10,000 resamples clustered by task, existing diagnostics algorithm and seed",
        },
        "groups": {},
    }
    if bundle is not None:
        phase, identity = verified_phase(bundle, pin, worklist)
        result["regenerationSourceCommit"] = identity["sourceCommit"]
    intervals = []
    for group in worklist["groups"]:
        source = group["historicalRun"]
        archived = read_inputs(REPO / source["directory"])
        pins = report_bindings(archived, source["fileSha256"])
        tally = summarize_records(archived)
        verify_archived_tally(group, tally, references)
        if bundle is None:
            item = {"archiveReadbackMatches": True, "archived": tally, "archivedFilesSha256": pins}
        else:
            captured, hashes, comparison, interval = capture_comparison(group, archived, bundle, phase, identity)
            item = {"archiveReadbackMatches": True,
                    "archived": tally, "archivedFilesSha256": pins,
                    "regenerated": summarize_records(captured), "regeneratedFilesSha256": hashes,
                    "alignment": public_alignment(comparison)}
            intervals.append(interval)
        result["groups"][group["id"]] = item
    intervals.sort()
    require(all(right[0] >= left[1] for left, right in zip(intervals, intervals[1:])),
            "recorded regeneration launches overlap")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--archive-self-check", action="store_true")
    mode.add_argument("--regeneration-bundle", type=Path)
    parser.add_argument("--phase-receipt-sha256", help="independently reviewed phase-result.json SHA-256")
    parser.add_argument("--out", type=Path, help="write a new report without overwriting an existing file")
    args = parser.parse_args()
    if bool(args.regeneration_bundle) != bool(args.phase_receipt_sha256):
        parser.error("a regeneration bundle and its reviewed phase receipt SHA-256 are a pair")
    try:
        bundle = args.regeneration_bundle.resolve(strict=True) if args.regeneration_bundle else None
        if bundle is not None:
            require(bundle.is_dir() and bundle.is_relative_to(REPO.parent), "regeneration bundle must be AIJADE-local")
        output = encoded(report(prepare(), bundle, args.phase_receipt_sha256))
        if args.out is not None:
            with args.out.open("xb") as stream:
                stream.write(output)
        sys.stdout.buffer.write(output)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        parser.exit(2, f"{exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
