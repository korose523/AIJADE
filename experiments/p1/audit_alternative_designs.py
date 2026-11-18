#!/usr/bin/env python3
"""Reconcile the recorded P1-A cases across configurations without running faults."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from code_fault_summary import KEYS, group


ROOT = Path(__file__).resolve().parent
INPUT_FILE = "alternative-designs.json"
CODE_FILE = "alternative-designs-code-faults.json"
ARCHIVES = {
    INPUT_FILE: (
        "29a527107e9e2758ea4579b190dec88bea895b9a",
        "de70ae570448e6152b490dc81714b113630e3b06",
        "dbd75fee2d4ddc33721d0a7d64edc9ffbb48fa48cc61ba3da02d6f6250e4f8bb",
    ),
    CODE_FILE: (
        "6d85e4a68158e431cbb8863c5bb5f87ac2cb9db9",
        "7d119a9f1443938deda4b98e1d6881bb4be0e9c4",
        "f8e905b1420fc65c8180ebb328c175a426076e086d93e1e2928aad3162edc78b",
    ),
}
INPUT_GROUP_SIZES = {"1": 24, "2": 5, "3": 9, "valid": 24}
CODE_GROUP_SIZES = {
    "changed unit or meaning": 5,
    "drift-matrix mutants": 18,
    "gate-matrix mutants": 15,
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(body):
    return hashlib.sha256(body).hexdigest()


def read_archive(name, body):
    _, code_commit, digest = ARCHIVES[name]
    require(sha256(body) == digest, f"{name}: archived bytes differ")
    data = json.loads(body)
    require(data["codeCommit"] == code_commit, f"{name}: unexpected recorded code revision")
    return data


def count(value):
    return type(value) is int and value >= 0


def input_groups(rows):
    groups = {name: {configuration: {} for configuration in KEYS} for name in INPUT_GROUP_SIZES}
    for row in rows:
        cohort, configuration, case = (row[k] for k in ("set", "configuration", "id"))
        require(cohort in groups and configuration in KEYS, "unknown input cohort or configuration")
        arm = groups[cohort][configuration]
        require(type(case) is str and case and case not in arm, "duplicate or invalid input case")
        require(type(row["detected"]) is bool and ((row["point"] != "none") == row["detected"]),
                "invalid recorded input disposition")
        require(all(count(row[key]) for key in ("eventsWritten", "tracesWritten")),
                "invalid input row-count delta")
        arm[case] = row
    for cohort, arms in groups.items():
        expected = arms[KEYS[0]]
        require(len(expected) == INPUT_GROUP_SIZES[cohort], f"wrong denominator for input cohort {cohort}")
        for arm in arms.values():
            require(arm.keys() == expected.keys(), f"unpaired input cases in cohort {cohort}")
            for case, row in arm.items():
                require(all(row[k] == expected[case][k] for k in ("class", "form", "kind")),
                        f"input case {cohort}/{case} differs across configurations")
    return groups


def input_arm_summary(arm):
    detected = {case: row for case, row in arm.items() if row["detected"]}
    return {
        "cases": len(arm),
        "detected": len(detected),
        "detectedIds": sorted(detected),
        "detectionStages": dict(Counter(row["point"] for row in detected.values())),
        "detectedCasesWithRowDelta": sorted(
            case for case, row in detected.items() if row["eventsWritten"] or row["tracesWritten"]
        ),
        "eventRowDeltaOverDetectedCases": sum(row["eventsWritten"] for row in detected.values()),
        "traceRowDeltaOverDetectedCases": sum(row["tracesWritten"] for row in detected.values()),
    }


def input_pair_summary(arms, summaries):
    paper, liberal, contracts, lineage = KEYS
    paper_ids = set(summaries[paper]["detectedIds"])
    lineage_ids = set(summaries[lineage]["detectedIds"])
    return {
        "firstThreeDetectExactlySameCases": all(
            set(summaries[key]["detectedIds"]) == paper_ids for key in (liberal, contracts)
        ),
        "changedStagesAmongSharedDetections": {
            other: {
                case: {"comparator": arms[other][case]["point"], "paper": arms[paper][case]["point"]}
                for case in sorted(paper_ids & set(summaries[other]["detectedIds"]))
                if arms[other][case]["point"] != arms[paper][case]["point"]
            }
            for other in (liberal, contracts)
        },
        "paperAndLineage": {
            "both": sorted(paper_ids & lineage_ids),
            "paperOnly": sorted(paper_ids - lineage_ids),
            "lineageOnly": sorted(lineage_ids - paper_ids),
        },
    }


def code_groups(rows):
    groups = {name: {} for name in CODE_GROUP_SIZES}
    for row in rows:
        name, case = group(row), row["id"]
        require(type(case) is str and case and case not in groups[name], "duplicate or invalid code-fault case")
        require(row["set"] in ("2", "3") and set(row["cells"]) == set(KEYS), "unpaired code-fault cells")
        for cell in row["cells"].values():
            detected = cell["detected"]
            require(detected is None or type(detected) is bool, "invalid code-fault disposition")
            if detected is None:
                require(cell["point"] == "not applicable" and "eventsWritten" not in cell,
                        "invalid inapplicable code-fault cell")
            else:
                require(cell["point"] != "not applicable" and ((cell["point"] != "none") == detected)
                        and count(cell["eventsWritten"]), "invalid applicable code-fault cell")
        groups[name][case] = row["cells"]
    require(all(len(rows) == CODE_GROUP_SIZES[name] for name, rows in groups.items()),
            "wrong code-fault group denominator")
    return groups


def code_group_summary(name, rows, archived_table):
    table = {"faults": len(rows)}
    by_configuration = {}
    for key in KEYS:
        applicable = {case: cells[key] for case, cells in rows.items() if cells[key]["detected"] is not None}
        detected = {case: cell for case, cell in applicable.items() if cell["detected"]}
        stages = Counter(cell["point"] for cell in detected.values())
        table[key] = {
            "applicable": len(applicable),
            "detected": len(detected),
            "points": dict(Counter(cell["point"].split(":")[0] for cell in detected.values())),
            "missed": [case for case in applicable if case not in detected],
        }
        by_configuration[key] = {
            "applicable": len(applicable),
            "detected": len(detected),
            "detectedIds": sorted(detected),
            "notApplicableIds": sorted(rows.keys() - applicable.keys()),
            "detectionStages": dict(stages),
        }
    require(table == archived_table, f"{name}: supplied code table disagrees with recorded cells")
    return by_configuration


def audit(input_archive, code_archive):
    inputs = input_groups(input_archive["rows"])
    code = code_groups(code_archive["rows"])
    require(set(code_archive["table"]) == set(code), "unexpected code-fault summary groups")
    input_summaries = {
        name: {key: input_arm_summary(arm) for key, arm in arms.items()}
        for name, arms in inputs.items()
    }
    code_summaries = {
        name: code_group_summary(name, rows, code_archive["table"][name]) for name, rows in code.items()
    }
    applicable = sum(arm["applicable"] for arms in code_summaries.values() for arm in arms.values())
    return {
        "schema": "aijade.p1.alternative-designs-paired-readback.v1",
        "scope": "Descriptive recomputation of the original P1-A rows. No fault, runtime, or model was run.",
        "sources": {
            name: {"archiveCommit": archive, "recordedCodeCommit": code_commit, "sha256": digest}
            for name, (archive, code_commit, digest) in ARCHIVES.items()
        },
        "population": {
            "inputScenarioKeys": sum(INPUT_GROUP_SIZES.values()),
            "inputConfigurationRows": len(input_archive["rows"]),
            "codeFaultRows": len(code_archive["rows"]),
            "codeConfigurationCells": len(code_archive["rows"]) * len(KEYS),
            "applicableCodeCells": applicable,
            "notApplicableCodeCells": len(code_archive["rows"]) * len(KEYS) - applicable,
        },
        "inputAndData": input_summaries,
        "set1Paired": input_pair_summary(inputs["1"], input_summaries["1"]),
        "codeFaults": code_summaries,
        "interpretation": [
            "Recorded stages and row-count deltas are properties of these authored cases.",
            "Row deltas cover whole trajectories, including accepted setup events. They do not classify the rows as faulty.",
            "Code-fault applicability and the historical non-blind timing of the consumer tests are retained.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", type=Path, help="compare the exact computed bytes with a receipt")
    args = parser.parse_args()
    inputs, code = (read_archive(name, (ROOT / name).read_bytes()) for name in (INPUT_FILE, CODE_FILE))
    encoded = (json.dumps(audit(inputs, code), indent=2, sort_keys=True) + "\n").encode()
    if args.verify is None:
        print(encoded.decode(), end="")
    else:
        require(args.verify.read_bytes() == encoded, "paired readback differs from the receipt")
        print(f"PASS {sha256(encoded)}")


if __name__ == "__main__":
    main()
