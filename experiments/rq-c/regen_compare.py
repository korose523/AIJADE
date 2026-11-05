#!/usr/bin/env python3
"""Compare a regenerated RQ-C run with its archive, step by step (experiments/plans/2026-11-04-p2-r-regeneration.md, steps 2 and 4).

Records are aligned by step and skill identifier, separately for each condition. For every aligned step: are the generated
reply, the extracted code, the verifier reply, the verdict and the execution result identical? Later steps of a condition depend
on earlier replies, so the first divergent step and the identical steps before it are reported; after a divergence a condition
is compared through its summary only. A shorter regenerated run (the determinism check's --trials 5) is compared on the steps
it has, with the archive's steps of the trials it holds.

  usage: python3 -I experiments/rq-c/regen_compare.py --archived DIR --regenerated DIR [--out FILE]
"""
import argparse
import collections
import hashlib
import json
import os
import sys

CONDITIONS = ("sv0-ef0", "sv0-ef1", "sv1-ef0", "sv1-ef1")
FIELDS = (("generation", "generation"), ("code", "code"), ("verifierReply", "selfRationale"))


def load(run):
    trials = [json.loads(x) for x in open(os.path.join(run, "trials.jsonl"), encoding="utf-8")]
    cands = [json.loads(x) for x in open(os.path.join(run, "candidates.jsonl"), encoding="utf-8")]
    if len(trials) != len(cands) or any(a["skillId"] != b["skillId"] for a, b in zip(trials, cands)):
        sys.exit(f"{run}: trials and candidates are not aligned")
    by = collections.defaultdict(list)
    for t, c in zip(trials, cands):
        by[t["condition"]].append((t, c))
    return by


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def rates(rows):
    skills = {}
    for t, _ in rows:
        s = skills.setdefault(t["skillId"], {"verdict": t["selfVerdict"], "last": None})
        s["last"] = t["execOk"]
    judged = [s for s in skills.values() if s["verdict"] is not None]
    unusable = [s for s in judged if not s["last"]]
    usable = [s for s in judged if s["last"]]
    return {"skills": len(skills), "judged": len(judged), "falsePass": [sum(s["verdict"] == "pass" for s in unusable), len(unusable)],
            "falseFail": [sum(s["verdict"] == "fail" for s in usable), len(usable)]}


def compare(archived, regenerated):
    conditions = {}
    for cond in CONDITIONS:
        a, b = archived.get(cond, []), regenerated.get(cond, [])
        n = min(len(a), len(b))
        first = None
        for i in range(n):
            ta, ca = a[i]
            tb, cb = b[i]
            diffs = []
            if ta["skillId"] != tb["skillId"]:
                diffs.append("skillId")
            diffs += [name for name, key in FIELDS if ca.get(key) != cb.get(key)]
            if ta["selfVerdict"] != tb["selfVerdict"]:
                diffs.append("verdict")
            if ta["execOk"] != tb["execOk"]:
                diffs.append("execution")
            if diffs:
                first = {"step": i, "skill": tb["skillId"], "differs": diffs, "archived": {k: ca.get(k) for _, k in FIELDS}, "regenerated": {k: cb.get(k) for _, k in FIELDS}}
                break
        conditions[cond] = {"archivedSteps": len(a), "regeneratedSteps": len(b), "identicalSteps": n if first is None else first["step"], "firstDivergence": first,
                            "archivedSummary": rates(a[:n]), "regeneratedSummary": rates(b[:n])}
    return conditions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archived", required=True)
    ap.add_argument("--regenerated", required=True)
    ap.add_argument("--out")
    args = ap.parse_args()
    conditions = compare(load(args.archived), load(args.regenerated))
    out = {
        "plan": "experiments/plans/2026-11-04-p2-r-regeneration.md",
        "planCommit": "3f380be",
        "deviation": "The plan says its code is written after its PDF goes to the supervisor; on the first author's decision of 5 November 2026 it was written before.",
        "codeCommit": os.environ.get("AIJADE_GIT_COMMIT"),
        "inputs": {side: {f: sha(os.path.join(d, f)) for f in ("trials.jsonl", "candidates.jsonl")} for side, d in (("archived", args.archived), ("regenerated", args.regenerated))},
        "identical": all(c["firstDivergence"] is None for c in conditions.values()),
        "conditions": conditions,
    }
    text = json.dumps(out, ensure_ascii=False, indent=1) + "\n"
    if args.out:
        open(args.out, "w", encoding="utf-8").write(text)
    print(json.dumps({"identical": out["identical"], "identicalSteps": {k: v["identicalSteps"] for k, v in conditions.items()}}))


if __name__ == "__main__":
    main()
