#!/usr/bin/env python3
"""P1-A's code faults: the driver's rows and baseline into one results file. Usage: code_fault_summary.py <rows.jsonl> <golden log> <commit> <out.json>"""
import collections
import json
import sys

KEYS = ["1 paper", "2 liberal", "3 contracts", "4 lineage"]


def group(r):
    if r["set"] == "2":
        return "changed unit or meaning"
    return "drift-matrix mutants" if r["id"].startswith("FU-") else "gate-matrix mutants"


def main():
    rows_path, golden_path, commit, target = sys.argv[1:5]
    rows = [json.loads(line) for line in open(rows_path, encoding="utf-8")]
    baseline = json.load(open(rows_path + ".baseline.json", encoding="utf-8"))
    golden = set(open(golden_path, encoding="utf-8").read().splitlines())
    table = {}
    for g in ("changed unit or meaning", "drift-matrix mutants", "gate-matrix mutants"):
        part = [r for r in rows if group(r) == g]
        table[g] = {"faults": len(part)}
        for k in KEYS:
            applicable = [r for r in part if r["cells"][k]["detected"] is not None]
            points = collections.Counter(r["cells"][k]["point"].split(":")[0] for r in applicable if r["cells"][k]["detected"])
            table[g][k] = {"applicable": len(applicable), "detected": sum(points.values()), "points": dict(points),
                           "missed": [r["id"] for r in applicable if not r["cells"][k]["detected"]]}
    report = {
        "experiment": "P1-A: faults defined on code against four configurations",
        "plan": "experiments/plans/2026-11-05-p1-a-alternative-designs.md (addendum)",
        "codeCommit": commit,
        "database": "PostgreSQL 18.0",
        "ranOn": "2026-11-05 to 2026-11-06",
        "deviations": [
            "The consumer tests and the five changed-meaning faults came after the input faults had run, by the same researcher, against the plan's Code version rule; the faults were fixed before the tests were written, so the tests are not a blind test of any configuration.",
            "No code reads the values of spans or time_spans, so the plan's example could not be given as written; C1 and C2 are the nearest forms.",
            "Two earlier passes were not kept as results: one stopped on a stale catalogue match, and one left warnings as errors, so that 15 mutants did not build.",
            "Rule kept as fixed: kernel-schema faults count as not applicable in configurations 3 and 4, although the runtime still builds its proposal through that schema, so FU-06 makes consumer tests fail; see the row's raw checks.",
            "The worker is not started, so rows read by a downstream consumer other than the projection are not measured.",
        ],
        "checks": {"consumerTests": 11, "consumerTestLines": 216, "writingTimeRecorded": False,
                   "driftAssertionsDroppedForLiberal": sum(line in golden for line in baseline["contradictedByLiberal"]),
                   "driftAssertions": len(golden), "contradictedByLiberal": baseline["contradictedByLiberal"]},
        "table": table,
        "rows": rows,
    }
    with open(target, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(json.dumps(table, indent=None), report["checks"]["driftAssertionsDroppedForLiberal"], report["checks"]["driftAssertions"])


if __name__ == "__main__":
    main()
