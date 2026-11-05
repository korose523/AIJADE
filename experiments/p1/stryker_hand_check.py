#!/usr/bin/env python3
"""P1-B, check of the tool's outcomes: apply each surviving mutant in static code by hand and run its matrix test.

Each mutant's replacement is written into a copy of the checkout at the location the tool reported, the matrix's test
project is built there, its one test runs, and the source file is restored. Writes one JSON line per mutant, and resumes.
Usage: stryker_hand_check.py <copy of the run branch> <dir with the tool's reports> <output .jsonl>
"""
import json
import os
import subprocess
import sys

RUNS = {"drift-server": "Drift", "drift-core": "Drift", "drift-memory": "Drift", "gate-server": "Gate", "gate-memory": "Gate"}
FILES = {"drift-server": ["V9/Boundary.cs", "V9/V9Endpoints.cs", "V9/V9EventService.cs"], "drift-memory": ["Kernel/Events.cs"],
         "drift-core": ["Schema/WireSchema.cs"], "gate-server": ["V9/PromotionService.cs"],
         "gate-memory": ["V9/ShadowParams.cs", "Development/Vse.cs", "Pgc/PgcGate.cs"]}


def apply(text, loc, replacement):
    lines = text.split("\n")
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line) + 1)
    start = offsets[loc["start"]["line"] - 1] + loc["start"]["column"] - 1
    end = offsets[loc["end"]["line"] - 1] + loc["end"]["column"] - 1
    return text[:start] + replacement + text[end:]


def main():
    copy, reports, target = sys.argv[1:4]
    done = set()
    if os.path.exists(target):
        with open(target, encoding="utf-8") as f:
            done = {json.loads(line)["key"] for line in f}
    env = dict(os.environ, DOTNET_CLI_UI_LANGUAGE="en")
    for run, project in RUNS.items():
        with open(f"{reports}/{run}/reports/mutation-report.json", encoding="utf-8") as f:
            report = json.load(f)
        for path, entry in report["files"].items():
            if not any(path.endswith("/" + name) for name in FILES[run]):
                continue
            relative = path.split("/p1b-check/")[1]
            source = os.path.join(copy, relative)
            for m in entry["mutants"]:
                key = f"{run}:{m['id']}"
                if not (m.get("static") and m["status"] == "Survived") or key in done:
                    continue
                with open(source, encoding="utf-8", newline="") as f:
                    original = f.read()
                with open(source, "w", encoding="utf-8", newline="") as f:
                    f.write(apply(original, m["location"], m.get("replacement", "")))
                row = {"key": key, "run": run, "file": relative, "line": m["location"]["start"]["line"], "mutator": m["mutatorName"], "replacement": m.get("replacement", "")[:120]}
                try:
                    build = subprocess.run(["dotnet", "build", f"tests/P1b.{project}", "-c", "Release", "--nologo", "-v", "q"], cwd=copy, env=env, capture_output=True, text=True, timeout=600)
                    if build.returncode != 0:
                        row["hand"] = "CompileError"
                    else:
                        try:
                            test = subprocess.run(["./Aijade.Tests"], cwd=f"{copy}/tests/P1b.{project}/bin/Release/net10.0", env=env, capture_output=True, text=True, timeout=300)
                            row["hand"] = "Survived" if test.returncode == 0 else "Killed"
                        except subprocess.TimeoutExpired:
                            row["hand"] = "Timeout"
                finally:
                    with open(source, "w", encoding="utf-8", newline="") as f:
                        f.write(original)
                with open(target, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
