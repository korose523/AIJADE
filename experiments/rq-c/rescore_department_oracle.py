#!/usr/bin/env python3
"""Interpret reviewed P2-R exploratory replay evidence.

The manifest mode emits the exact input, phase, rule and program identities.
Produce derives a transcript from independently pinned per-case observations
and a typed evaluator receipt. Score re-derives the transcript from those same
inputs before interpreting its outcomes. Synthetic evidence requires explicit
synthetic mode in both stages.
"""

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import re
import sys

from department_oracle_capture import read_capture
from department_oracle_evidence import SKIPPED, TRANSCRIPT_SCHEMA, VARIANTS, produce_transcript
from launch_department_regeneration import file_pin
from oracle_audit import BENCH, BENCH_SHA256, DROPPED, NODE_REPLAY, TEST_AUDIT, clustered_mcnemar, diagnostics
from prepare_department_regeneration import HERE, REPO, encoded, prepare, require, sha
from regen_compare_v2 import SHA256, load_rows, read_inputs, validate_summary
from summarize_department_regeneration import (
    ARCHIVED_LABELS, MODEL_PINS, Skill, capture_comparison, report_bindings, verified_phase,
)


ORACLE_SOURCE_SHA256 = "d790d9ddaa8a7425d0b8bc945e97007dce8c96d94444be47ab0fbda08275a349"
REPORT_SCHEMA = "aijade.p2-r.department-exploratory-oracle-report.v1"
OUTCOMES = frozenset({"PASSED", "FAILED_CASES", "NO_CALLABLE", "SETUP_ERROR", "TIMEOUT"})
HISTORICAL_BCA_ABSOLUTE_TOLERANCE = 1e-12
HISTORICAL_CLUSTERED_P_RELATIVE_TOLERANCE = 1e-12


def rule_contract():
    file_pin(HERE / "oracle_audit.py", ORACLE_SOURCE_SHA256)
    pinned = file_pin(REPO / BENCH, BENCH_SHA256)
    bench = json.loads(pinned.read_bytes())
    tasks = {}
    for task in bench["tasks"]:
        base_cases = task["tests"]
        keep = [i for i, case in enumerate(base_cases) if case["args"] not in DROPPED.get(task["id"], ())]
        raw_timeout = task.get("timeoutMs")
        timeout = 2000 if raw_timeout is None else raw_timeout
        require(type(timeout) is int and timeout > 0, "pinned task timeout is invalid")
        tasks[task["id"]] = {
            "timeoutMs": timeout,
            "casesSha256": sha(encoded(base_cases)),
            "caseIndices": list(range(len(base_cases))),
            "entryAndTestCaseIndices": keep,
        }
    require(len(tasks) == TEST_AUDIT["tasks"]
            and sum(len(row["caseIndices"]) for row in tasks.values()) == TEST_AUDIT["casesRead"]
            and sum(len(row["caseIndices"]) - len(row["entryAndTestCaseIndices"]) for row in tasks.values()) == 1,
            "pinned task and exclusion counts differ")
    return {
        "schema": "aijade.p2-r.department-oracle-rules.v1",
        "oracleSourceSha256": ORACLE_SOURCE_SHA256,
        "referenceReplayEngineSha256": sha(NODE_REPLAY.encode()),
        "benchSha256": BENCH_SHA256,
        "tasks": tasks,
        "variants": list(VARIANTS),
        "entryRule": "use the historical lexical entry fallback after the original resolution attempts",
        "removedCaseArgs": DROPPED,
        "candidateIdentity": "task id and SHA-256 of exact UTF-8 extracted code",
        "outcomes": sorted(OUTCOMES),
        "skippedStatus": SKIPPED,
        "judgedTruth": "last recorded execution, or a successful replay under the applicable exploratory rule",
        "skillSuccess": "at least half of recorded calls succeeded, or replay passed under the applicable rule",
        "taskBootstrap": {"resamples": 10000, "seed": 0x2545F491},
    }


def captured_skills(inputs, tasks):
    summary = validate_summary(inputs["summary.json"])
    config = summary["config"]
    rows = load_rows(inputs, config["rounds"], config["tasks"])
    per_cell = config["trials"] * config["rounds"] * config["tasks"]
    require(all(len(records) == per_cell for records in rows.values()), "incomplete oracle input population")
    skills = {}
    for cell, records in rows.items():
        for record, candidate in records:
            skill_id, task = record["skillId"], record["taskId"]
            require(task in tasks, "recorded task is not in the pinned bench")
            identity = (cell, record["trial"], task, record["selfVerdict"], candidate["code"])
            skill = skills.get(skill_id)
            require(record["reused"] is (skill is not None), "oracle input skill reuse order differs")
            if skill is None:
                skill = skills[skill_id] = Skill(identity)
            require(skill.identity == identity, "recorded task, verdict or code changed within a skill")
            skill.calls += 1
            skill.successes += record["execOk"]
            skill.last_execution_ok = record["execOk"]
    require(type(summary["nSkills"]) is int and summary["nSkills"] == len(skills)
            and type(summary["nExecutions"]) is int and summary["nExecutions"] == sum(map(len, rows.values())),
            "reported oracle input denominators differ")
    return skills


def program_key(task, code):
    return task, sha(code.encode())


def program_population(skills):
    programs = defaultdict(list)
    for skill in skills.values():
        _, _, task, _, code = skill.identity
        programs[program_key(task, code)].append(skill)
    return programs


def historical_skip(code):
    # The canonical lexical skip is a retained disposition, not an execution policy.
    pattern = re.search(r"^const RISKY = /(.+)/;$", NODE_REPLAY, re.MULTILINE)
    require(pattern is not None, "canonical replay disposition is unavailable")
    return re.search(pattern[1], code, re.ASCII) is not None


def scores(skills, replay):
    def trial_success(state):
        return 2 * state["succ"] >= state["calls"]

    states = []
    for skill in skills.values():
        cell, trial, task, verdict, code = skill.identity
        states.append({"task": task, "key": program_key(task, code), "trial": trial,
                       "sv": cell.startswith("sv1"), "ef": cell.endswith("ef1"),
                       "verdict": verdict, "calls": skill.calls, "succ": skill.successes,
                       "last": skill.last_execution_ok})
    output = {}
    for index, variant in enumerate(VARIANTS):
        def gained(state):
            outcomes = replay[state["key"]]
            return index > 0 and outcomes is not None and outcomes[index]

        def success(state):
            return trial_success(state) or gained(state)

        judged = []
        distinct = {}
        by_task = defaultdict(set)
        for state in states:
            task = state["task"]
            by_task[task].add(success(state))
            if state["verdict"] is None:
                continue
            row = (task, state["verdict"] == "pass", state["last"] or gained(state))
            judged.append(row)
            distinct.setdefault(state["key"], row)
        unusable = [row for row in distinct.values() if not row[2]]
        false_passes = [row for row in unusable if row[1]]
        output[variant] = {
            "diagnostics": diagnostics(judged),
            "distinct": {"candidates": len(distinct), "unusable": len(unusable),
                         "unusableTasks": len({row[0] for row in unusable}),
                         "falsePasses": len(false_passes), "falsePassTasks": len({row[0] for row in false_passes})},
            "clusteredMcNemar": clustered_mcnemar(states, success),
            "informativeTasks": sorted(task for task, outcomes in by_task.items() if len(outcomes) == 2),
        }
    return output


def historical_label_mismatch(actual, expected, path=()):
    """Report the first mismatch while bounding rounding at computed libm fields."""
    field = ".".join(map(str, path)) or "labels"
    if type(actual) is not type(expected):
        return f"{field}: type {type(actual).__name__} != {type(expected).__name__}"
    if type(actual) is dict:
        if set(actual) != set(expected):
            return f"{field}: field names differ"
        for key, value in actual.items():
            mismatch = historical_label_mismatch(value, expected[key], (*path, key))
            if mismatch is not None:
                return mismatch
        return None
    if type(actual) is list:
        if len(actual) != len(expected):
            return f"{field}: length {len(actual)} != {len(expected)}"
        for index, (value, reference) in enumerate(zip(actual, expected)):
            mismatch = historical_label_mismatch(value, reference, (*path, index))
            if mismatch is not None:
                return mismatch
        return None
    if actual == expected:
        return None
    if type(actual) is float:
        if (len(path) == 5 and path[0] in VARIANTS and path[1] == "diagnostics"
                and path[3] == "taskBootstrapBca95" and path[4] in (0, 1)
                and math.isclose(actual, expected, rel_tol=0, abs_tol=HISTORICAL_BCA_ABSOLUTE_TOLERANCE)):
            return None
        if (len(path) == 3 and path[0] in VARIANTS and path[1:] == ("clusteredMcNemar", "clusteredP")
                and math.isclose(actual, expected, rel_tol=HISTORICAL_CLUSTERED_P_RELATIVE_TOLERANCE, abs_tol=0)):
            return None
        return f"{field}: numeric delta {abs(actual - expected):.17g}"
    return f"{field}: value differs"


def historical_labels_match(actual, expected):
    return historical_label_mismatch(actual, expected) is None


def archive_readback(worklist, contract):
    pin = MODEL_PINS["oracle-audit.json"]
    archive = json.loads(file_pin(HERE / "oracle-audit.json", pin).read_bytes())
    require(archive["bench"]["sha256"] == contract["benchSha256"], "historical oracle bench differs")
    by_slug = {run["slug"]: run for run in archive["runs"]}
    output = {}
    for group in worklist["groups"]:
        source = group["historicalRun"]
        inputs = read_inputs(REPO / source["directory"])
        hashes = report_bindings(inputs, source["fileSha256"])
        slug = ARCHIVED_LABELS[group["id"]][1]
        prior = by_slug[slug]
        require(all(hashes[key] == value for key, value in prior["hashes"].items()), "oracle archive input hash differs")
        skills = captured_skills(inputs, contract["tasks"])
        population = program_population(skills)
        historical = prior["replay"]
        require(historical == {"distinctPrograms": len(population), "notReplayed": 0,
                               "disagreementsOnJudgedSkills": 0, "disagreementsOnAllSkills": 0},
                "retained witnesses cannot reconstruct this historical baseline")
        winners = []
        for name in ("entryClass", "testClass"):
            entries = prior[name]
            selected = {program_key(row["task"], row["code"]) for row in entries}
            require(len(entries) == len(selected) and selected <= set(population), "historical witness population differs")
            winners.append(selected)
        require(not winners[0] & winners[1], "historical promotion classes overlap")
        decisions = {}
        for key, states in population.items():
            outcomes = {state.last_execution_ok for state in states}
            require(len(outcomes) == 1 and not historical_skip(states[0].identity[4]),
                    "retained historical program has ambiguous recorded execution")
            baseline = outcomes.pop()
            require(not baseline or key not in (winners[0] | winners[1]), "historical promotion is already usable")
            decisions[key] = (baseline, baseline or key in winners[0],
                              baseline or key in winners[0] or key in winners[1])
        labels = scores(skills, decisions)
        mismatch = historical_label_mismatch(labels, prior["labels"])
        require(mismatch is None, f"{group['id']}: historical exploratory tables do not reproduce: {mismatch}")
        output[group["id"]] = {
            "archiveFilesSha256": hashes,
            "source": "retained promotion classes and historical replay agreement",
            "labels": labels,
            "retainedFailureWitnesses": prior["soleFailingCaseOfJudgedSkills"],
            "promotions": {"entry": len(winners[0]), "additionalTestExclusion": len(winners[1])},
            "programs": len(population),
        }
    return output


def accepted_population(bundle, pin, worklist, contract):
    phase, runner = verified_phase(bundle, pin, worklist)
    groups, manifest, intervals = {}, {}, []
    for group in worklist["groups"]:
        source = group["historicalRun"]
        archive = read_inputs(REPO / source["directory"])
        report_bindings(archive, source["fileSha256"])
        captured, hashes, _, interval = capture_comparison(group, archive, bundle, phase, runner)
        skills = captured_skills(captured, contract["tasks"])
        programs = program_population(skills)
        group_id = group["id"]
        groups[group_id] = (skills, programs)
        manifest[group_id] = {
            "captureFilesSha256": hashes,
            "programs": [{"taskId": task, "codeSha256": digest,
                          "historicalSkipApplies": historical_skip(programs[(task, digest)][0].identity[4])}
                         for task, digest in sorted(programs)],
        }
        intervals.append(interval)
    intervals.sort()
    require(all(right[0] >= left[1] for left, right in zip(intervals, intervals[1:])),
            "recorded regeneration launches overlap")
    identity = {"phaseReceiptSha256": pin, "worklistSha256": runner["worklistSha256"],
                "sourceCommit": runner["sourceCommit"], "runnerSha256": runner["runnerSha256"],
                "ruleContractSha256": sha(encoded(contract))}
    return {"binding": identity, "groups": manifest}, groups


def checked_outcome(row, indices):
    require(type(row) is dict and isinstance(row.get("outcome"), str) and row["outcome"] in OUTCOMES,
            "unknown oracle replay outcome")
    state = row["outcome"]
    wanted = {"outcome", "failedCaseIndices"}
    if state == "TIMEOUT":
        wanted.add("timedOutCaseIndex")
    require(set(row) == wanted, "incomplete oracle case evidence")
    failed = row["failedCaseIndices"]
    require(type(failed) is list and all(type(index) is int for index in failed)
            and failed == sorted(set(failed)) and set(failed) <= set(indices),
            "failed case indices are unordered, repeated or excluded")
    if state == "TIMEOUT":
        timed = row["timedOutCaseIndex"]
        require(type(timed) is int and timed in indices and all(index < timed for index in failed),
                "timeout does not follow the completed case prefix")
    elif state == "FAILED_CASES":
        require(bool(failed), "case failure needs a retained case")
    else:
        require(not failed, "setup, missing entry or passing outcomes cannot contain case failures")
    return state


def interpret_transcript(transcript, manifest, groups, contract):
    require(transcript["schema"] == TRANSCRIPT_SCHEMA and transcript["manifestSha256"] == sha(encoded(manifest))
            and transcript["binding"] == manifest["binding"] and set(transcript["groups"]) == set(groups),
            "replay transcript is for different inputs, rules or phase")
    require(isinstance(transcript.get("reviewedEvaluatorReceiptSha256"), str)
            and SHA256.fullmatch(transcript["reviewedEvaluatorReceiptSha256"]),
            "reviewed evaluator evidence digest is missing")
    output = {}
    for group_id, (skills, programs) in groups.items():
        item = transcript["groups"][group_id]
        require(item["captureFilesSha256"] == manifest["groups"][group_id]["captureFilesSha256"]
                and type(item["programs"]) is list and len(item["programs"]) == len(programs),
                f"{group_id}: replay transcript population or capture hashes differ")
        replay = {}
        counters = {variant: defaultdict(int) for variant in VARIANTS}
        replay_mismatch = 0
        for row in item["programs"]:
            task = row["taskId"]
            key = task, row["codeSha256"]
            require(key in programs and key not in replay, f"{group_id}: unknown or duplicated program")
            skipped = historical_skip(programs[key][0].identity[4])
            require(row["status"] == (SKIPPED if skipped else "CAPTURED"),
                    f"{group_id}: replay skip does not match the historical disposition")
            common = {"taskId", "codeSha256", "status"}
            require(set(row) == (common if skipped else common | set(VARIANTS)),
                    f"{group_id}: replay variant evidence is incomplete")
            if skipped:
                replay[key] = None
                continue
            task_rule = contract["tasks"][task]
            outcomes = []
            for variant in VARIANTS:
                indices = task_rule["entryAndTestCaseIndices" if variant == "entryAndTest" else "caseIndices"]
                outcome = checked_outcome(row[variant], indices)
                counters[variant][outcome] += 1
                outcomes.append(outcome == "PASSED")
            for skill in programs[key]:
                if skill.last_execution_ok != outcomes[0]:
                    require(skill.identity[3] is None, f"{group_id}: baseline replay disagrees on a judged skill")
                    replay_mismatch += 1
            replay[key] = tuple(outcomes)
        output[group_id] = {
            "programs": len(replay), "historicalSkips": sum(value is None for value in replay.values()),
            "baselineDisagreementsOnUnjudgedSkills": replay_mismatch,
            "outcomesByVariant": {variant: dict(sorted(counts.items())) for variant, counts in counters.items()},
            "labels": scores(skills, replay),
        }
    return output


def local_file(path, label):
    absolute = path.absolute()
    require(absolute.is_relative_to(REPO.parent) and absolute.resolve() == absolute,
            f"{label} must be an unredirected AIJADE-local path")
    return absolute


def pinned_bytes(path, pin, label):
    source = local_file(path, label)
    require(SHA256.fullmatch(pin) and source.is_file() and not source.is_symlink(),
            f"file identity differs: {source.name}")
    raw = source.read_bytes()
    require(sha(raw) == pin, f"file identity differs: {source.name}")
    return raw


def reviewed_replay(args, manifest_document, phase_closed_at=None, regeneration_approval_pin=None):
    synthetic = args.evidence_mode == "synthetic"
    scope = "SYNTHETIC_FIXTURE" if synthetic else "OPERATOR_REVIEWED_EXTERNAL_REPLAY"
    manifest_raw = pinned_bytes(args.replay_manifest, args.replay_manifest_sha256, "replay manifest")
    raw_capture = (args.capture_directory, args.operator_review, args.operator_review_sha256)
    fixture_only = (args.observations, args.observations_sha256, args.evaluator_receipt, args.evaluator_receipt_sha256)
    capture = None
    if any(raw_capture):
        require(all(raw_capture) and not any(fixture_only),
                "supply the complete operator-reviewed capture inputs as one evidence route")
        capture = read_capture(local_file(args.capture_directory, "capture directory"),
                               pinned_bytes(args.operator_review, args.operator_review_sha256, "operator review"),
                               manifest_document, manifest_raw, scope, phase_closed_at, regeneration_approval_pin)
        observations_raw = encoded(capture["observations"])
        evaluator_raw = encoded(capture["evaluatorReceipt"])
    else:
        require(synthetic and args.action != "capture" and all(fixture_only),
                "external replay requires the complete operator-reviewed case capture")
        observations_raw = pinned_bytes(args.observations, args.observations_sha256, "observations")
        evaluator_raw = pinned_bytes(args.evaluator_receipt, args.evaluator_receipt_sha256, "evaluator receipt")
    transcript = produce_transcript(manifest_document, manifest_raw, observations_raw, evaluator_raw, scope)
    if capture is not None:
        transcript["captureProvenance"] = capture["provenance"]
    return transcript, capture


def report_header(worklist, contract):
    return {"schema": REPORT_SCHEMA, "ruleContract": contract, "ruleContractSha256": sha(encoded(contract)),
            "retainedOracleAuditSha256": MODEL_PINS["oracle-audit.json"],
            "historicalBcaAbsoluteTolerance": HISTORICAL_BCA_ABSOLUTE_TOLERANCE,
            "historicalClusteredPRelativeTolerance": HISTORICAL_CLUSTERED_P_RELATIVE_TOLERANCE,
            "worklistSha256": sha(encoded(worklist)), "formalRunsStartedByReport": 0,
            "candidateExecutionsByReport": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("archive-self-check", "manifest", "capture", "produce", "score"):
        command = commands.add_parser(action)
        command.add_argument("--out", type=Path, help="write a new report without overwriting an existing file")
        if action != "archive-self-check":
            command.add_argument("--regeneration-bundle", type=Path, required=True)
            command.add_argument("--phase-receipt-sha256", required=True)
        if action in ("capture", "produce", "score"):
            command.add_argument("--replay-manifest", type=Path, required=True)
            command.add_argument("--replay-manifest-sha256", required=True)
            command.add_argument("--capture-directory", type=Path)
            command.add_argument("--operator-review", type=Path)
            command.add_argument("--operator-review-sha256")
            command.add_argument("--observations", type=Path, help="direct synthetic fixtures only")
            command.add_argument("--observations-sha256")
            command.add_argument("--evaluator-receipt", type=Path, help="direct synthetic fixtures only")
            command.add_argument("--evaluator-receipt-sha256")
            command.add_argument("--evidence-mode", choices=("external", "synthetic"), default="external")
        if action == "score":
            command.add_argument("--replay-transcript", type=Path, required=True)
            command.add_argument("--replay-transcript-sha256", required=True)
    args = parser.parse_args()
    try:
        worklist = prepare()
        contract = rule_contract()
        result = report_header(worklist, contract)
        if args.action == "archive-self-check":
            result.update(scope="RETAINED_EXPLORATORY_ARCHIVE_SELF_CHECK", groups=archive_readback(worklist, contract))
        else:
            bundle = args.regeneration_bundle.resolve(strict=True)
            require(bundle.is_dir() and bundle.is_relative_to(REPO.parent), "regeneration bundle must be AIJADE-local")
            manifest, groups = accepted_population(bundle, args.phase_receipt_sha256, worklist, contract)
            result.update(manifest=manifest, manifestSha256=sha(encoded(manifest)))
            if args.action == "manifest":
                result["scope"] = "REPLAY_MANIFEST_ONLY"
            else:
                synthetic = args.evidence_mode == "synthetic"
                phase_closed_at, regeneration_approval_pin = None, None
                if args.capture_directory is not None:
                    phase_raw = pinned_bytes(bundle / "phase-result.json", args.phase_receipt_sha256, "phase receipt")
                    phase = json.loads(phase_raw)
                    phase_closed_at = phase["observationFinishedAt"]
                    regeneration_approval_pin = phase.get("approvalSha256")
                transcript, capture = reviewed_replay(args, dict(result, scope="REPLAY_MANIFEST_ONLY"),
                                                      phase_closed_at, regeneration_approval_pin)
                if args.action == "capture":
                    result = capture
                elif args.action == "produce":
                    result = transcript
                else:
                    raw = pinned_bytes(args.replay_transcript, args.replay_transcript_sha256, "replay transcript")
                    require(raw == encoded(transcript), "reviewed transcript differs from the observed case results")
                    regenerated = interpret_transcript(transcript, manifest, groups, contract)
                    result.update(scope=("SYNTHETIC_REPLAY_TRANSCRIPT_SCORED" if synthetic
                                         else "EXPLORATORY_REPLAY_TRANSCRIPT_SCORED"),
                                  evidenceScope=transcript["evidenceScope"],
                                  replayTranscriptSha256=args.replay_transcript_sha256,
                                  observationsFileSha256=transcript["observationsFileSha256"],
                                  reviewedEvaluatorReceiptSha256=transcript["reviewedEvaluatorReceiptSha256"],
                                  reviewedEvaluatorIdentity=transcript["reviewedEvaluatorIdentity"],
                                  retainedArchiveGroups=archive_readback(worklist, contract), groups=regenerated)
                    if capture is not None:
                        result["captureProvenance"] = capture["provenance"]
        payload = encoded(result)
        if args.out is not None:
            with local_file(args.out, "report output").open("xb") as target:
                target.write(payload)
        sys.stdout.buffer.write(payload)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        parser.exit(2, f"{exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
