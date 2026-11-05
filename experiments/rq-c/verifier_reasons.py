#!/usr/bin/env python3
"""What the verifier said when it judged: a re-tally of the recorded RQ-C main run (5 November 2026).

EXPLORATORY AND AFTER THE FACT, like oracle_audit.py next to it: no plan preceded it, every result of the runs was known, and
the coding below was made by one reader after reading the replies. It reads only recorded files and makes no model calls.
The programs are replayed in Node's vm with oracle_audit.py's mirror of the sandbox, only to list which test cases each
program fails. The labels stay the run's own.

For every distinct program the main run's verifier rejected, the reply's stated reason is coded against the code, the
instruction and the replayed failures (CODING). A reply that accepts a program is counted as bare when it says only PASS.

  usage (from the repository root): python3 -I experiments/rq-c/verifier_reasons.py [--out experiments/rq-c/verifier-reasons.json]
"""
import argparse
import collections
import hashlib
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = {
    "main": "redo/rq-c-s42-ollama-t30-r5",
    "templateA": "template-gpu/A/rq-c-s42-ollama-t30-r5",
}

# Keys: task, then the first 12 hex digits of the SHA-256 of the program text. Codes:
#   false-of-code    the reason attributes to the program a behavior it does not have
#   true-of-code     the reason states a behavior the program has, and that behavior is why it fails or departs from the instruction
#   partly           one clause holds and another does not
#   calling-rule     the reason is the function's name: the instruction names one, the generation prompt asks for `solve`
#   undetermined     the reason concerns the input the instruction does not determine (oracle_audit.py, DROPPED)
CODING = {
    ("arr-flatten", "one-level"): "false-of-code",
    ("arr-flatten", "one-level-branch"): "false-of-code",
    ("arr-flatten", "flat-no-arg"): "true-of-code",
    ("arr-flatten", "flat-1"): "partly",
    ("arr-intersection", "set-filter"): "partly",
    ("arr-intersection", "set-delete"): "partly",
    ("parse-query-string", "value-or-empty"): "false-of-code",
    ("str-to-camel", "lowercases-first"): "undetermined",
    ("str-to-camel", "keeps-first"): "undetermined",
    ("logic-roman-to-int", "named-solve"): "calling-rule",
}
PROGRAM_NAMES = {  # a substring of the program identifies it within its task
    ("arr-flatten", "one-level"): "Array.isArray(val) ? val : [val]",
    ("arr-flatten", "one-level-branch"): "Array.isArray(val) ? acc.concat(val) : acc.concat(val)",
    ("arr-flatten", "flat-no-arg"): "val.flat() : val",
    ("arr-flatten", "flat-1"): "val.flat(1) : val",
    ("arr-intersection", "set-filter"): "a.filter(item => setB.has(item));",
    ("arr-intersection", "set-delete"): "!setB.delete(item)",
    ("parse-query-string", "value-or-empty"): "value ? decodeURIComponent(value) : ''",
    ("str-to-camel", "lowercases-first"): "index === 0 ? word.toLowerCase()",
    ("str-to-camel", "keeps-first"): "s.replace(/[-_](.)/g, (_, c) => c.toUpperCase());",
    ("logic-roman-to-int", "named-solve"): "const roman = {",
}


def load_audit():
    spec = importlib.util.spec_from_file_location("oracle_audit", os.path.join(HERE, "oracle_audit.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def skills_of(directory):
    base = os.path.join(HERE, directory)
    trials = [json.loads(line) for line in open(os.path.join(base, "trials.jsonl"), encoding="utf-8")]
    cands = [json.loads(line) for line in open(os.path.join(base, "candidates.jsonl"), encoding="utf-8")]
    if len(trials) != len(cands) or any(a["skillId"] != b["skillId"] for a, b in zip(trials, cands)):
        sys.exit(f"{directory}: trials and candidates are not aligned")
    by_id = {}
    for t, c in zip(trials, cands):
        s = by_id.setdefault(t["skillId"], {"task": t["taskId"], "code": c["code"], "verdict": t["selfVerdict"],
                                            "why": c["selfRationale"], "last": None})
        s["last"] = t["execOk"]
    return [s for s in by_id.values() if s["verdict"] is not None]


def bare(reply):
    return (reply or "").strip().upper().rstrip(".") == "PASS"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "verifier-reasons.json"))
    args = ap.parse_args()
    audit = load_audit()
    root = os.path.dirname(os.path.dirname(HERE))
    bench = json.load(open(os.path.join(root, audit.BENCH), encoding="utf-8"))
    tasks = {t["id"]: {"tests": [{"args": c["args"], "expected": c["expected"]} for c in t["tests"]], "timeoutMs": t.get("timeoutMs")}
             for t in bench["tasks"]}

    judged = skills_of(RUNS["main"])
    counts = collections.Counter((s["verdict"], s["last"]) for s in judged)
    if (counts[("pass", True)], counts[("pass", False)], counts[("fail", True)], counts[("fail", False)]) != (654, 59, 78, 80):
        sys.exit(f"main run: confusion counts differ from p2-models.json: {counts}")

    programs = collections.OrderedDict()
    for s in judged:
        if s["verdict"] != "fail":
            continue
        e = programs.setdefault((s["task"], s["code"]), {"usable": s["last"], "skills": 0, "reasons": collections.Counter()})
        if e["usable"] != s["last"]:
            sys.exit(f"{s['task']}: one program with two labels")
        e["skills"] += 1
        e["reasons"][s["why"]] += 1

    pairs = list(programs)
    r = subprocess.run(["node", "-e", audit.NODE_REPLAY], input=json.dumps({"tasks": tasks, "pairs": [list(p) for p in pairs], "dropped": {}}),
                       capture_output=True, text=True, check=True)
    replay = json.loads(r.stdout)

    rows = []
    used = set()
    for (task, code), rep in zip(pairs, replay):
        keys = [k for k, sub in PROGRAM_NAMES.items() if k[0] == task and sub in code]
        if len(keys) != 1:
            sys.exit(f"{task}: {len(keys)} program names match {code[:70]!r}")
        used.add(keys[0])
        e = programs[(task, code)]
        rows.append({
            "task": task,
            "program": keys[0][1],
            "codeSha256": hashlib.sha256(code.encode()).hexdigest()[:12],
            "usable": e["usable"],
            "skills": e["skills"],
            "failingCases": rep["asRun"]["failing"],
            "reasons": [{"text": w, "skills": n} for w, n in e["reasons"].most_common()],
            "code": CODING[keys[0]],
        })
    if used != set(CODING):
        sys.exit(f"coded programs not seen: {set(CODING) - used}")

    by_code = collections.Counter()
    for row in rows:
        by_code[("usable" if row["usable"] else "unusable", row["code"])] += row["skills"]

    template_a = skills_of(RUNS["templateA"])
    out = {
        "experiment": "Verifier replies of the RQ-C main run against the code and the instruction (re-tally, no model calls)",
        "status": "Exploratory, after every result was known; no plan preceded it; one reader coded the reasons.",
        "coding": {
            "false-of-code": "the reason attributes to the program a behavior it does not have",
            "true-of-code": "the reason states a behavior the program has, which is why it fails",
            "partly": "one clause of the reason holds and another does not",
            "calling-rule": "the reason is the function's name: the instruction names one, the generation prompt asks for solve",
            "undetermined": "the reason concerns the input the instruction does not determine (str-to-camel, 'Hello-World')",
        },
        "main": {
            "judged": len(judged),
            "accepted": sum(1 for s in judged if s["verdict"] == "pass"),
            "acceptedBare": sum(1 for s in judged if s["verdict"] == "pass" and bare(s["why"])),
            "falsePasses": counts[("pass", False)],
            "falsePassesBare": sum(1 for s in judged if s["verdict"] == "pass" and not s["last"] and bare(s["why"])),
            "rejected": sum(1 for s in judged if s["verdict"] == "fail"),
            "rejectedPrograms": len(rows),
            "falseFailsByCode": {c: n for (side, c), n in sorted(by_code.items()) if side == "usable"},
            "trueFailsByCode": {c: n for (side, c), n in sorted(by_code.items()) if side == "unusable"},
            "programs": rows,
        },
        "templateA": {
            "judged": len(template_a),
            "accepted": sum(1 for s in template_a if s["verdict"] == "pass"),
            "acceptedBare": sum(1 for s in template_a if s["verdict"] == "pass" and bare(s["why"])),
        },
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(json.dumps({k: v for k, v in out["main"].items() if k != "programs"}, ensure_ascii=False))
    for row in rows:
        print(row["task"], row["program"], "usable" if row["usable"] else "unusable", row["skills"], row["code"],
              [c.get("args") for c in row["failingCases"]])


if __name__ == "__main__":
    main()
