#!/usr/bin/env python3
"""P1-B, results: the tool's reports plus the hand check of surviving static mutants, scored as the plan fixes.

Usage: stryker_summary.py <dir with the tool's reports and hand-check.jsonl> <repo> <plan commit> <base commit of the files> <out.json>
Score: K / (K + S + N), and K / (K + S) over executed mutants, each with a Wilson 95% interval that treats mutants as units.
The hand outcome replaces the tool's where the two differ; compile errors, timeouts and ignored mutants are only counted.
"""
import collections
import json
import math
import re
import subprocess
import sys

RUNS = {"drift-server": "drift", "drift-core": "drift", "drift-memory": "drift", "gate-server": "gate", "gate-memory": "gate"}
AREAS = {"Boundary.cs": "http-boundary", "V9Endpoints.cs": "http-boundary", "V9EventService.cs": "http-boundary",
         "Events.cs": "kernel-validation", "WireSchema.cs": "kernel-validation",
         "PromotionService.cs": "promotion-and-gates", "ShadowParams.cs": "promotion-and-gates", "Vse.cs": "promotion-and-gates", "PgcGate.cs": "promotion-and-gates"}
P1A_FILES = ["src/Aijade.Server/V9/Boundary.cs", "src/Aijade.Server/V9/V9Endpoints.cs", "src/Aijade.Server/V9/V9EventService.cs"]


def wilson(k, n, z=1.959964):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def added_lines(repo, base, plan):
    """Lines of the plan's commit that P1-A's switches added, by file."""
    added = {}
    for name in P1A_FILES:
        diff = subprocess.run(["git", "-C", repo, "diff", "-U0", base, plan, "--", name], capture_output=True, text=True, check=True).stdout
        lines = set()
        for m in re.finditer(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", diff, re.M):
            start, count = int(m.group(1)), int(m.group(2) or 1)
            lines.update(range(start, start + count))
        added[name] = lines
    return added


def score(rows):
    c = collections.Counter(r["final"] for r in rows)
    k, s, n = c["Killed"], c["Survived"], c["NoCoverage"]
    out = {"killed": k, "survived": s, "noCoverage": n, "compileError": c["CompileError"], "timeout": c["Timeout"], "ignored": c["Ignored"]}
    out["score"] = round(k / (k + s + n), 4) if k + s + n else None
    out["scoreCi95"] = wilson(k, k + s + n)
    out["executedScore"] = round(k / (k + s), 4) if k + s else None
    out["executedScoreCi95"] = wilson(k, k + s)
    return out


def main():
    out_dir, repo, plan, base, target = sys.argv[1:6]
    hand = {}
    with open(f"{out_dir}/hand-check.jsonl", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            hand[row["key"]] = row["hand"]
    added = added_lines(repo, base, plan)
    rows, tool_version = [], None
    for run, matrix in RUNS.items():
        with open(f"{out_dir}/{run}/reports/mutation-report.json", encoding="utf-8") as f:
            report = json.load(f)
        for path, entry in report["files"].items():
            relative = path.split("/p1b-check/")[1]
            name = relative.rsplit("/", 1)[1]
            if name not in AREAS:
                continue
            for m in entry["mutants"]:
                key = f"{run}:{m['id']}"
                line = m["location"]["start"]["line"]
                rows.append({"key": key, "matrix": matrix, "area": AREAS[name], "file": name, "line": line, "mutator": m["mutatorName"],
                             "static": bool(m.get("static")), "tool": m["status"], "hand": hand.get(key), "final": hand.get(key) or m["status"],
                             "onP1aLine": line in added.get(relative, ())})
    missing = set(hand) - {r["key"] for r in rows}
    assert not missing, missing

    def group(rows_, field):
        return {v: score([r for r in rows_ if r[field] == v]) for v in sorted({r[field] for r in rows_})}

    result = {
        "experiment": "P1-B: detection power of the drift and gate matrices on an independently constructed fault set",
        "plan": "experiments/plans/2026-11-05-p1-b-independent-fault-set.md",
        "planCommit": plan,
        "runBranch": "p1-b-run",
        "runCommit": open(f"{out_dir}/run-commit.txt", encoding="utf-8").read().strip(),
        "tool": "Stryker.NET 5.0.0 (dotnet-stryker), test runner mtp, one test project per matrix",
        "database": "PostgreSQL 18.0",
        "machine": "Mac, x86_64, 8 CPUs, 16 GB, other containers running",
        "ranOn": "2026-11-05",
        "handWrittenScores": {"drift": {"score": 0.50, "mutants": "9 of 18 executable"}, "gate": {"all": 0.65, "reachable": 0.87}},
        "notes": [
            "Mutants are the units of the Wilson intervals: a description of this mutant set, not a population estimate.",
            "Scores are not pooled with the hand-written ones, whose criterion differs: a mutant counted only when an assertion line turned red.",
            "The tool cannot mutate const values, so faults in const declarations are not generated.",
            "Control of the hand check: the unmutated copy passed three runs of each matrix test after the last mutant.",
        ],
        "handCheck": {
            "applied": len(hand),
            "killed": sum(1 for v in hand.values() if v == "Killed"),
            "survived": sum(1 for v in hand.values() if v == "Survived"),
            "differencesFromTool": sum(1 for r in rows if r["hand"] and r["hand"] != r["tool"]),
        },
        "toolOutcomesBeforeHandCheck": {m: score([{**r, "final": r["tool"]} for r in rows if r["matrix"] == m]) for m in ("drift", "gate")},
        "byMatrix": group(rows, "matrix"),
        "byMatrixWithoutP1aLines": group([r for r in rows if not r["onP1aLine"]], "matrix"),
        "onP1aLines": score([r for r in rows if r["onP1aLine"]]),
        "byArea": group(rows, "area"),
        "byFile": group(rows, "file"),
        "equivalentByHand": [],
        "uncaughtByOperator": {m: dict(collections.Counter(r["final"] for r in rows if r["mutator"] == m and r["final"] in ("Survived", "NoCoverage"))) for m in sorted({r["mutator"] for r in rows})},
        "mutantColumns": ["key", "file", "line", "mutator", "static", "tool", "hand", "onP1aLine"],
        "mutants": [[r["key"], r["file"], r["line"], r["mutator"], r["static"], r["tool"], r["hand"], r["onP1aLine"]] for r in rows],
    }
    with open(target, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(json.dumps({k: result[k] for k in ("handCheck", "toolOutcomesBeforeHandCheck", "byMatrix", "byMatrixWithoutP1aLines", "onP1aLines", "byArea", "byFile")}, indent=None))


if __name__ == "__main__":
    main()
