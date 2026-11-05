#!/usr/bin/env python3
"""P2-A stage 1: what MultiPL-E's JavaScript sets hold, against the compatibility screen of stage 0.

Reads the row files fetched from the Hugging Face datasets server, runs nothing, and writes multiple-check.json.
Usage: multiple_check.py <dir with humaneval-js-*.json and mbpp-js-*.json> <listing of datasets/mbpp-typed> <output>
"""
import glob
import hashlib
import json
import re
import subprocess
import sys


def rows(folder, config):
    out = []
    for name in sorted(glob.glob(f"{folder}/{config}-*.json"), key=lambda n: int(re.search(r"-(\d+)\.json", n).group(1))):
        with open(name, encoding="utf-8") as f:
            out += [r["row"] for r in json.load(f)["rows"]]
    return out


def task_number(name):
    return int(re.match(r"(?:HumanEval|mbpp)_(\d+)_", name).group(1))


def features(row):
    tests = row["tests"]
    prompt = row["prompt"]
    asserts = re.findall(r"assert\.(\w+)\(", tests)
    return {
        "garbledWordInPrompt": "jsthon" in prompt.lower(),
        "undefinedInTests": "undefined" in tests,
        "assertForms": sorted(set(asserts)),
        "testCount": len(asserts),
        "promptEndsInSignature": prompt.rstrip().endswith("{"),
    }


def main():
    folder, listing, target = sys.argv[1], sys.argv[2], sys.argv[3]
    with open("experiments/p2-a/evalplus-compatibility.json", encoding="utf-8") as f:
        screen = json.load(f)["datasets"]
    report = {
        "experiment": "P2-A stage 1: MultiPL-E's JavaScript sets against the compatibility screen",
        "plan": "experiments/plans/2026-11-05-p2-a-candidate-diversity.md",
        "source": "nuprl/MultiPL-E on the Hugging Face datasets server, configurations humaneval-js and mbpp-js, split test; fetched 5 November 2026",
        "gitCommit": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip(),
        "ranNothing": "No test, candidate or model was run; the tests were read as text.",
    }
    sets = {}
    for config, plus, prefix in [("humaneval-js", "HumanEval+", "HumanEval/"), ("mbpp-js", "MBPP+", "Mbpp/")]:
        data = rows(folder, config)
        digest = hashlib.sha256(json.dumps(sorted(data, key=lambda r: r["name"]), sort_keys=True).encode()).hexdigest()
        have = {task_number(r["name"]) for r in data}
        per = {int(t["taskId"].split("/")[1]): t for t in screen[plus]["perTask"]}
        feats = [features(r) for r in data]
        forms = {}
        for f in feats:
            for a in f["assertForms"]:
                forms[a] = forms.get(a, 0) + 1
        by_class = {}
        for number, task in per.items():
            entry = by_class.setdefault(task["class"], {"screened": 0, "withStatement": 0, "missing": []})
            entry["screened"] += 1
            if number in have:
                entry["withStatement"] += 1
            else:
                entry["missing"].append(task["taskId"])
        names = {r["name"]: r for r in data}
        sets[config] = {
            "tasks": len(data),
            "rowsSha256": digest,
            "promptsWithGarbledWord": sorted(r["name"] for r, f in zip(data, feats) if f["garbledWordInPrompt"]),
            "testsMentioningUndefined": sum(f["undefinedInTests"] for f in feats),
            "assertFormsByTask": forms,
            "testsPerTaskMedian": sorted(f["testCount"] for f in feats)[len(feats) // 2],
            "promptsNotEndingInSignature": sum(not f["promptEndsInSignature"] for f in feats),
            "screenClasses": by_class,
            "statementTerminology": sorted({r["prompt_terminology"] for r in data}),
            "doctestModes": sorted({r["doctests"] for r in data}),
        }
        if config == "mbpp-js":
            with open(listing, encoding="utf-8") as f:
                source = {re.search(r"/(mbpp_(\d+)_[^/]+)\.py$", line).group(1) for line in f if line.strip().endswith(".py")}
            sets[config]["sourceFiles"] = len(source)
            sets[config]["notTranslated"] = sorted(s for s in source if s not in names)
        else:
            sets[config]["absentNumbers"] = sorted(set(range(164)) - have)
    report["sets"] = sets
    with open(target, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")
    for k, v in sets.items():
        print(k, {a: (b if not isinstance(b, (list, dict)) else (len(b) if a.startswith("prompts") else b)) for a, b in v.items() if a != "screenClasses"})
        print({c: (e["screened"], e["withStatement"], e["missing"][:6]) for c, e in v["screenClasses"].items()})


if __name__ == "__main__":
    main()
