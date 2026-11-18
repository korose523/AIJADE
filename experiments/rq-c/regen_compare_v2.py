#!/usr/bin/env python3
"""Compare completed P2-R records without treating an interrupted prefix as identity.

The historical comparator and its reports retain their original schema and bytes.
This successor only reads pre-existing run artifacts. By default it compares the
complete archived population. Use --qualification-trials explicitly to compare a
smaller, complete qualification run with the corresponding recorded prefix.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


CONDITIONS = ("sv0-ef0", "sv0-ef1", "sv1-ef0", "sv1-ef1")
DIMENSIONS = ("trials", "rounds", "tasks")
SHA256 = re.compile(r"[a-f0-9]{64}")
UINT_MAX = (1 << 32) - 1
INPUT_NAMES = ("trials.jsonl", "candidates.jsonl", "summary.json")


def read_inputs(directory):
    return {
        name: path.read_bytes() if path.is_file() else None
        for name in INPUT_NAMES
        for path in (directory / name,)
    }


def validate_summary(data):
    summary = json.loads(data)
    if not isinstance(summary, dict) or not isinstance(summary.get("config"), dict):
        raise ValueError("summary.json must contain its run configuration")
    config = summary["config"]
    integer_fields = (*DIMENSIONS, "pruneMinCalls", "maxReplyTokens", "numCtx")
    for field in integer_fields:
        if type(config.get(field)) is not int or config[field] < 1:
            raise ValueError(f"summary.config.{field} must be a positive integer")
    seed = config.get("seed")
    if type(seed) is not int or not 0 <= seed <= UINT_MAX:
        raise ValueError("summary.config.seed must be an unsigned 32-bit integer")
    for field in ("pCorrect", "pruneThreshold"):
        value = config.get(field)
        if type(value) not in (int, float) or not 0 <= value <= 1:
            raise ValueError(f"summary.config.{field} must be a probability")
    model = config.get("model")
    if config.get("backend") != "ollama" or not isinstance(model, str) or not model.strip():
        raise ValueError("summary.config must identify the Ollama backend and a model")
    if config.get("domain") != "executable":
        raise ValueError("summary.config.domain must be executable")
    temperature = config.get("temperature", 0)
    if type(temperature) not in (int, float) or not 0 <= temperature <= 2:
        raise ValueError("summary.config.temperature must be a number within [0, 2]")
    for field in ("inert", "verdictFallback"):
        if field in config and config[field] is not True:
            raise ValueError(f"summary.config.{field} must be true when present")
    if config.get("verifyTemplate", "A") not in ("A", "B"):
        raise ValueError("summary.config.verifyTemplate must be A or B")
    if "taskAllocation" in config and config["taskAllocation"] != "balanced-permutation-v1":
        raise ValueError("summary.config.taskAllocation must name the recorded allocation rule")
    for field in ("publicBankManifestSha256", "builtinBankManifestSha256", "requestPolicySha256"):
        value = config.get(field)
        if field in config and (not isinstance(value, str) or not SHA256.fullmatch(value)):
            raise ValueError(f"summary.config.{field} must be a SHA-256")
    if summary.get("conditions") != list(CONDITIONS):
        raise ValueError("summary.json does not record the four expected conditions in order")

    sampling = summary.get("sampling")
    if not isinstance(sampling, dict) or sampling.get("mode") != "live":
        raise ValueError("summary.sampling must describe the Ollama requests")
    actual_temperature = sampling.get("temperature")
    if (sampling.get("model") != model
            or type(actual_temperature) not in (int, float) or actual_temperature != temperature):
        raise ValueError("summary.sampling model and temperature must match the run configuration")
    actual_seed = sampling.get("seed")
    expected_seed = ((seed ^ 0x9E3779B9) * 0x85EBCA6B) & UINT_MAX
    if type(actual_seed) is not int or actual_seed != expected_seed:
        raise ValueError("summary.sampling.seed must match the seed derived by the runner")
    digest = sampling.get("modelDigest")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise ValueError("summary.sampling.modelDigest must be a SHA-256")
    return summary


def decode_lines(data):
    return [] if data is None else [json.loads(line) for line in data.splitlines()]


def load_rows(inputs, rounds, tasks):
    trials = decode_lines(inputs["trials.jsonl"])
    candidates = decode_lines(inputs["candidates.jsonl"])
    if len(trials) != len(candidates):
        raise ValueError("trials.jsonl and candidates.jsonl have different lengths")
    rows = {condition: [] for condition in CONDITIONS}
    coordinates = set()
    previous_condition = -1
    for step, (trial, candidate) in enumerate(zip(trials, candidates)):
        if not isinstance(trial, dict) or not isinstance(candidate, dict):
            raise ValueError(f"step {step}: expected trial and candidate objects")
        condition = trial.get("condition")
        if not isinstance(condition, str) or condition not in rows:
            raise ValueError(f"step {step}: unexpected condition")
        condition_index = CONDITIONS.index(condition)
        if condition_index < previous_condition:
            raise ValueError(f"step {step}: conditions out of order")
        previous_condition = condition_index
        ordinal = len(rows[condition])
        expected_trial, expected_round = divmod(ordinal // tasks, rounds)
        for field, expected in (("trial", expected_trial), ("round", expected_round)):
            if type(trial.get(field)) is not int or trial[field] != expected:
                raise ValueError(f"step {step}: unexpected {field} position")
        task = trial.get("taskId")
        skill = trial.get("skillId")
        if not all(isinstance(value, str) and value for value in (task, skill)):
            raise ValueError(f"step {step}: missing task or skill identifier")
        coordinate = (condition, expected_trial, expected_round, task)
        if coordinate in coordinates:
            raise ValueError(f"step {step}: duplicate task within a condition, trial and round")
        coordinates.add(coordinate)

        if type(candidate.get("step")) is not int or candidate["step"] != step:
            raise ValueError(f"step {step}: candidate step is not aligned")
        if candidate.get("skillId") != skill:
            raise ValueError(f"step {step}: candidate skill is not aligned")
        for field in ("reused", "execOk"):
            if type(trial.get(field)) is not bool or candidate.get(field) is not trial[field]:
                raise ValueError(f"step {step}: trial and candidate disagree on {field}")
        uses_verifier = condition.startswith("sv1-")
        verdicts = ("pass", "fail") if uses_verifier else (None,)
        if "selfVerdict" not in trial or trial["selfVerdict"] not in verdicts:
            raise ValueError(f"step {step}: missing or invalid self-verification verdict")
        if not isinstance(candidate.get("code"), str):
            raise ValueError(f"step {step}: missing or invalid candidate code")
        fresh_candidate = not trial["reused"]
        fresh_verification = uses_verifier and fresh_candidate
        for field, expected_text in (("generation", fresh_candidate), ("selfRationale", fresh_verification)):
            expected_type = str if expected_text else type(None)
            if field not in candidate or not isinstance(candidate[field], expected_type):
                raise ValueError(f"step {step}: missing or invalid candidate {field}")
        if "selfReply" in candidate and (not fresh_verification or not isinstance(candidate["selfReply"], str)):
            raise ValueError(f"step {step}: invalid recorded full verifier reply")
        rows[condition].append((trial, candidate))
    return rows


def comparison_fields(row):
    trial, candidate = row
    return {
        "trial": trial["trial"],
        "round": trial["round"],
        "taskId": trial["taskId"],
        "skillId": trial["skillId"],
        "reused": trial["reused"],
        "generation": candidate["generation"],
        "code": candidate["code"],
        "verifierReply": candidate.get("selfReply", candidate["selfRationale"]),
        "verifierRationale": candidate["selfRationale"],
        "verifierFullReplyRecorded": "selfReply" in candidate,
        "verdict": trial["selfVerdict"],
        "execution": trial["execOk"],
    }


def compare_condition(archived, regenerated, expected_archived, expected_regenerated):
    first = None
    for step, (a, b) in enumerate(zip(archived, regenerated)):
        left = comparison_fields(a)
        right = comparison_fields(b)
        differences = [name for name in left if left[name] != right[name]]
        if differences:
            first = {
                "step": step,
                "skill": right["skillId"],
                "differs": differences,
                "archived": {name: left[name] for name in differences},
                "regenerated": {name: right[name] for name in differences},
            }
            break
    shared = min(len(archived), len(regenerated))
    return {
        "archivedSteps": len(archived),
        "regeneratedSteps": len(regenerated),
        "expectedArchivedSteps": expected_archived,
        "expectedRegeneratedSteps": expected_regenerated,
        "sharedSteps": shared,
        "identicalPrefixSteps": shared if first is None else first["step"],
        "firstDivergence": first,
    }


def compare_inputs(archived, regenerated, qualification_trials=None):
    if archived["summary.json"] is None:
        raise ValueError("archived summary.json is required to bind the expected run population")
    archive_summary = validate_summary(archived["summary.json"])
    archive_config = archive_summary["config"]
    full_trials, rounds, tasks = (archive_config[key] for key in DIMENSIONS)
    trial_limit = full_trials if qualification_trials is None else qualification_trials
    if not 1 <= trial_limit <= full_trials:
        raise ValueError("qualification trials must be positive and cannot exceed archived trials")
    expected_archived = full_trials * rounds * tasks
    expected_regenerated = trial_limit * rounds * tasks

    if regenerated["summary.json"] is not None:
        regenerated_summary = validate_summary(regenerated["summary.json"])
        expected_config = dict(archive_config, trials=trial_limit)
        regenerated_config = regenerated_summary["config"]
        different = sorted(
            key for key in expected_config.keys() | regenerated_config.keys()
            if expected_config.get(key) != regenerated_config.get(key)
            or (key in expected_config) != (key in regenerated_config)
        )
        if different:
            raise ValueError(f"regenerated configuration differs: {', '.join(different)}")
        for field in ("seed", "modelDigest"):
            if archive_summary["sampling"][field] != regenerated_summary["sampling"][field]:
                raise ValueError(f"regenerated sampling.{field} differs from archive")
    else:
        regenerated_summary = None

    a = load_rows(archived, rounds, tasks)
    b = load_rows(regenerated, rounds, tasks)
    conditions = {
        condition: compare_condition(a[condition], b[condition], expected_archived, expected_regenerated)
        for condition in CONDITIONS
    }
    for rows, expected in ((a, expected_archived), (b, expected_regenerated)):
        if any(len(records) > expected for records in rows.values()):
            raise ValueError("recorded condition exceeds its expected population")
    for rows, summary in ((a, archive_summary), (b, regenerated_summary)):
        if summary is None:
            continue
        counts = {
            "nExecutions": sum(map(len, rows.values())),
            "nSkills": len({trial["skillId"] for records in rows.values() for trial, _ in records}),
        }
        for key, expected in counts.items():
            if type(summary.get(key)) is not int or summary[key] != expected:
                raise ValueError(f"summary.{key} does not match its aligned records")
    complete = all(
        data[name] is not None
        for data in (archived, regenerated)
        for name in INPUT_NAMES
    ) and all(
        row["archivedSteps"] == expected_archived and row["regeneratedSteps"] == expected_regenerated
        for row in conditions.values()
    )
    differs = any(row["firstDivergence"] is not None for row in conditions.values())
    return {
        "status": "INCOMPLETE" if not complete else "DIFFERENT" if differs else "IDENTICAL",
        "scope": "FULL_RUN" if qualification_trials is None else "QUALIFICATION_TRIALS",
        "complete": complete,
        "identical": complete and not differs,
        "population": {"archivedTrials": full_trials, "regeneratedTrials": trial_limit,
                       "rounds": rounds, "tasksPerTrial": tasks, "conditions": list(CONDITIONS)},
        "ollamaVersions": {
            side: summary["sampling"].get("ollamaVersion") if summary is not None else None
            for side, summary in (("archived", archive_summary), ("regenerated", regenerated_summary))
        },
        "conditions": conditions,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archived", required=True, type=Path)
    parser.add_argument("--regenerated", required=True, type=Path)
    parser.add_argument("--qualification-trials", type=int, help="explicit completed prefix trial count")
    parser.add_argument("--out", type=Path, help="new report path (refuses to overwrite)")
    args = parser.parse_args()
    try:
        archived = read_inputs(args.archived)
        regenerated = read_inputs(args.regenerated)
        report = {
            "schema": "aijade.p2-r-comparison.v2",
            "inputs": {
                side: {
                    name: None if content is None else hashlib.sha256(content).hexdigest()
                    for name, content in data.items()
                }
                for side, data in (("archived", archived), ("regenerated", regenerated))
            },
        }
        try:
            report.update(compare_inputs(archived, regenerated, args.qualification_trials))
        except ValueError as exc:
            report.update(status="INVALID", complete=False, identical=False, error=str(exc))
        text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.out is not None:
            with args.out.open("x", encoding="utf-8") as file:
                file.write(text)
        print(text, end="")
    except OSError as exc:
        parser.exit(2, f"{exc}\n")
    return {"IDENTICAL": 0, "DIFFERENT": 1, "INCOMPLETE": 2, "INVALID": 2}[report["status"]]


if __name__ == "__main__":
    sys.exit(main())
