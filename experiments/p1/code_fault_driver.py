#!/usr/bin/env python3
"""P1-A's code faults (addendum of experiments/plans/2026-11-05-p1-a-alternative-designs.md).

Each fault is an exact, single-occurrence replacement in a copy of the checkout. The copy is built and every check runs once;
the four configurations' outcomes follow from them by the plan's order. Resumes from the output file; stops if the unmutated
copy does not pass.
Usage: code_fault_driver.py <copy of the checkout> <output .jsonl> [baseline-only]
"""
import json
import os
import subprocess
import sys
import tempfile

PROJECT = "experiments/p1/code-faults/P1a.Checks"
DRIFT = "Aijade.Tests.ContractDriftMatrixTests.Matrix_log_equals_the_recorded_baseline_line_by_line"
GATE = "Aijade.Tests.PromotionGateMatrixTests.Tampered_candidates_are_refused_without_writes_and_the_control_and_probes_are_promoted"
LIBERAL = "Aijade.Tests.CodeFaultChecksTests.Liberal_matrix_writes_its_log"
WORKLOAD = "Aijade.Tests.CodeFaultChecksTests.Workload_posts_the_chain_to_one_configuration"
CONSUMER = "Aijade.Tests.ConsumerExpectationTests"
SETTINGS = {"1 paper": "", "2 liberal": "liberal", "3 contracts": "contracts", "4 lineage": "lineage"}
NOT_APPLICABLE = {"FU-01": "34", "FU-02": "34", "FU-06": "34", "FU-18": "34", "FU-03": "34", "FU-05": "34", "FU-17": "34", "FU-04": "234", "FU-13": "234",
                  "FU-07a": "4", "FU-07b": "4", "FU-08": "4", "FU-11": "4", "FU-14": "4"}


def run_test(copy, env, selector, is_class=False):
    extra = ["--filter-class", selector] if is_class else ["--filter-method", selector]
    try:
        p = subprocess.run(["./Aijade.Tests", *extra], cwd=f"{copy}/{PROJECT}/bin/Release/net10.0", env=env, capture_output=True, text=True, errors="replace", timeout=900)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    failed = [line.strip()[:160] for line in p.stdout.splitlines() if line.strip().startswith("failed ")]
    return p.returncode == 0, failed


def checks(copy, env, golden_lines, contradicted):
    with tempfile.TemporaryDirectory() as tmp:
        out = {}
        out["drift"], out["driftFailed"] = run_test(copy, env, DRIFT)
        out["gate"], out["gateFailed"] = run_test(copy, env, GATE)
        out["consumer"], out["consumerFailed"] = run_test(copy, env, CONSUMER, is_class=True)
        log = f"{tmp}/liberal.log"
        finished, _ = run_test(copy, {**env, "AIJADE_P1A_LIBERAL_LOG": log}, LIBERAL)
        if finished and os.path.exists(log):
            lines = open(log, encoding="utf-8").read().splitlines()
            kept = [a for a in lines if a not in contradicted]
            base = [a for a in golden_lines if a not in contradicted]
            out["liberalDrift"] = kept == base and not any(a.startswith("FAIL") for a in kept)
            out["liberalLines"] = lines
        else:
            out["liberalDrift"] = False
            out["liberalLines"] = None
        out["workload"] = {}
        for key, setting in SETTINGS.items():
            path = f"{tmp}/w-{setting or 'paper'}.json"
            run_test(copy, {**env, "AIJADE_P1A_SETTING": setting, "AIJADE_P1A_WORKLOAD_OUT": path}, WORKLOAD)
            out["workload"][key] = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None
    return out


def cell(key, c, fault_id):
    number = key[0]
    if number in NOT_APPLICABLE.get(fault_id, ""):
        return {"detected": None, "point": "not applicable"}
    pre = {"1": [("drift matrix", c["drift"]), ("gate matrix", c["gate"])], "2": [("drift matrix, liberal", c["liberalDrift"]), ("gate matrix", c["gate"])],
           "3": [("consumer tests", c["consumer"]), ("gate matrix", c["gate"])], "4": [("gate matrix", c["gate"])]}[number]
    for name, ok in pre:
        if not ok:
            return {"detected": True, "point": f"before deployment: {name}", "eventsWritten": 0}
    w = c["workload"][key]
    if w is None:
        return {"detected": True, "point": "workload did not complete", "eventsWritten": None}
    if w["refused"]:
        return {"detected": True, "point": f"workload: {w['refused']} refused", "eventsWritten": w["eventsWritten"]}
    if number == "4" and w["audit"]:
        return {"detected": True, "point": "after-the-fact audit", "eventsWritten": w["eventsWritten"], "audit": w["audit"][:6]}
    return {"detected": False, "point": "none", "eventsWritten": w["eventsWritten"]}


def build(copy, env):
    p = subprocess.run(["dotnet", "build", PROJECT, "-c", "Release", "--nologo", "-v", "q", "-p:TreatWarningsAsErrors=false"], cwd=copy, env=env, capture_output=True, text=True, errors="replace", timeout=900)
    return p.returncode == 0, p.stdout[-400:]


def main():
    copy, target = sys.argv[1:3]
    env = dict(os.environ, DOTNET_CLI_UI_LANGUAGE="en")
    ok, text = build(copy, env)
    assert ok, text
    golden = open(f"{copy}/tests/Aijade.Tests/Golden/p1/contract-drift.txt", encoding="utf-8").read().splitlines()
    first = checks(copy, env, golden, set())
    assert first["liberalLines"] is not None, "the liberal matrix did not finish"
    contradicted = sorted((set(golden) ^ set(first["liberalLines"])))
    base = checks(copy, env, golden, set(contradicted))
    print(json.dumps({k: base[k] for k in ("drift", "gate", "consumer", "liberalDrift", "consumerFailed", "driftFailed", "gateFailed")}, indent=0)[:1500])
    print("contradicted lines:", len(contradicted))
    print({k: (v and (v["refused"], v["statuses"], v["audit"][:3])) for k, v in base["workload"].items()})
    failed = not (base["drift"] and base["gate"] and base["consumer"] and base["liberalDrift"]) or any(v is None or v["refused"] or v["audit"] for v in base["workload"].values())
    with open(target + ".baseline.json", "w", encoding="utf-8") as f:
        json.dump({"contradictedByLiberal": contradicted, "baselinePassed": not failed, "workload": base["workload"]}, f, ensure_ascii=False, indent=1)
    if failed:
        sys.exit("the unmutated copy does not pass: stop")
    if len(sys.argv) > 3:
        return
    faults = []
    for name, part in (("experiments/p1/code-faults.json", "2"), ("tools/Aijade.Mutation/mutations.json", "3"), ("tools/Aijade.Mutation/gate-mutants.json", "3")):
        for m in json.load(open(f"{copy}/{name}", encoding="utf-8")):
            if m.get("implementable", True):
                faults.append({**m, "set": part})
    unreachable = set(json.load(open(f"{copy}/experiments/p1/code-faults/unreachable-gate-mutants.json", encoding="utf-8")))
    faults = [m for m in faults if m["id"] not in unreachable]
    # P1-A's switches rewrote this one line after the catalogue was written; the mutant is the same.
    for m in faults:
        if m["id"] == "FU-07b":
            m["match"] = "if (identityChecks && !string.IsNullOrEmpty(value) && envelopeIds.Contains(value))"
    for m in faults:
        text = open(os.path.join(copy, m["file"]), encoding="utf-8", newline="").read()
        assert text.count(m["match"]) == 1, m["id"]
    done = set()
    if os.path.exists(target):
        done = {json.loads(line)["id"] for line in open(target, encoding="utf-8")}
    for m in faults:
        source = os.path.join(copy, m["file"])
        original = open(source, encoding="utf-8", newline="").read()
        if m["id"] in done:
            continue
        open(source, "w", encoding="utf-8", newline="").write(original.replace(m["match"], m["replace"]))
        row = {"id": m["id"], "set": m["set"], "file": m["file"], "form": m.get("form") or m.get("note", "")}
        try:
            ok, text = build(copy, env)
            if not ok:
                row["build"] = "failed"
                row["buildTail"] = text[-200:]
            else:
                c = checks(copy, env, golden, set(contradicted))
                row["checks"] = {k: c[k] for k in ("drift", "gate", "consumer", "liberalDrift")}
                row["consumerFailed"] = c["consumerFailed"]
                row["cells"] = {key: cell(key, c, m["id"]) for key in SETTINGS}
        finally:
            open(source, "w", encoding="utf-8", newline="").write(original)
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("done", len(faults))


if __name__ == "__main__":
    main()
