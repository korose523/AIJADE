#!/usr/bin/env python3
"""Two-layer comparison of a regenerated P2-R run with its archive, as the department-server plan reports it
(docs P2-R_系服务器方案_20261118, "报告方式"; approved by the supervisor on 21 November 2026).

Generation layer: how many of the regenerated programs are byte for byte an archived program of the same task, and each
task's execution pass rate in both runs. The first divergent step is reported by regen_compare_v2.py and is not repeated.
Judgment layer: on programs that occur in both runs (same task, same code), whether the execution oracle and the
verifier's majority self-verdict agree across the runs.

Reads only trials.jsonl and candidates.jsonl of the two run directories; runs no model and no program.
Usage: two_layer_report.py ARCHIVED_RUN_DIR REGENERATED_RUN_DIR [--out FILE]
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path


def load(run):
    run = Path(run)
    read = lambda name: [json.loads(line) for line in open(run / name, encoding="utf-8-sig") if line.strip()]
    trials, candidates = read("trials.jsonl"), read("candidates.jsonl")
    if len(trials) != len(candidates):
        raise ValueError(f"{run}: {len(trials)} trials but {len(candidates)} candidates")
    rows = []
    for t, c in zip(trials, candidates):
        if t["skillId"] != c["skillId"] or t["execOk"] != c["execOk"]:
            raise ValueError(f"{run}: trial and candidate records disagree at skill {t['skillId']}")
        rows.append({"task": t["taskId"], "code": hashlib.sha256(c["code"].encode("utf-8")).hexdigest(),
                     "exec": t["execOk"], "verdict": t.get("selfVerdict")})
    return rows


def pass_rates(rows):
    tally = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        tally[r["task"]][0] += bool(r["exec"])
        tally[r["task"]][1] += 1
    return tally


def majorities(rows):
    votes = collections.defaultdict(collections.Counter)
    for r in rows:
        if r["verdict"] is not None:
            votes[(r["task"], r["code"])][r["verdict"]] += 1
    out = {}
    for key, counter in votes.items():
        top = counter.most_common()
        out[key] = None if len(top) > 1 and top[0][1] == top[1][1] else top[0][0]  # None marks a tie
    return out


def compare(archived, regenerated):
    arch_programs = {(r["task"], r["code"]) for r in archived}
    regen_programs = {(r["task"], r["code"]) for r in regenerated}
    a_rate, r_rate = pass_rates(archived), pass_rates(regenerated)
    oracle = collections.defaultdict(set)
    for r in archived:
        oracle[(r["task"], r["code"])].add(r["exec"])
    same = conflicting = 0
    for r in regenerated:
        key = (r["task"], r["code"])
        if key in oracle:
            if oracle[key] == {r["exec"]}:
                same += 1
            else:
                conflicting += 1
    a_maj, r_maj = majorities(archived), majorities(regenerated)
    shared = sorted(set(a_maj) & set(r_maj))
    ties = [k for k in shared if a_maj[k] is None or r_maj[k] is None]
    decided = [k for k in shared if k not in ties]
    return {
        "generationLayer": {
            "distinctPrograms": {"archived": len(arch_programs), "regenerated": len(regen_programs)},
            "regeneratedProgramsIdenticalToAnArchivedProgram": len(regen_programs & arch_programs),
            "regeneratedExecutionsOfSuchPrograms": sum((r["task"], r["code"]) in arch_programs for r in regenerated),
            "regeneratedExecutions": len(regenerated),
            "taskPassRates": {t: {"archived": f"{a_rate[t][0]}/{a_rate[t][1]}",
                                  "regenerated": f"{r_rate[t][0]}/{r_rate[t][1]}" if t in r_rate else None}
                              for t in sorted(set(a_rate) | set(r_rate))},
            "firstDivergence": "reported by regen_compare_v2.py",
        },
        "judgmentLayer": {
            "oracleOnIdenticalPrograms": {"sameVerdict": same, "conflicting": conflicting},
            "selfVerdictOnIdenticalPrograms": {
                "programsJudgedInBoth": len(shared), "tiedInEitherRun": len(ties),
                "sameMajority": sum(a_maj[k] == r_maj[k] for k in decided),
                "differentMajority": sum(a_maj[k] != r_maj[k] for k in decided)},
        },
        "unit": "program = (taskId, SHA-256 of the extracted code); oracle counts are regenerated executions",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("archived")
    parser.add_argument("regenerated")
    parser.add_argument("--out")
    args = parser.parse_args()
    report = compare(load(args.archived), load(args.regenerated))
    text = json.dumps(report, ensure_ascii=False, indent=1) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(json.dumps({k: {x: y for x, y in v.items() if x != "taskPassRates"} if isinstance(v, dict) else v
                      for k, v in report.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
