#!/usr/bin/env python3
"""Integrity audit of the RQ-C runs generated on the second host (plan: experiments/plans/2026-10-25-host-integrity-audit.md).

Reads only recorded files; no model calls. Generated code is parsed with Node's vm.Script, which compiles without running.
  usage (from the repository root): python3 -I experiments/rq-c/host_audit.py [--out experiments/rq-c/host-audit.json]
"""
import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys

PLAN = "experiments/plans/2026-10-25-host-integrity-audit.md"
RQC = "experiments/rq-c"
RUNS = [  # (label, host, directory, trials SHA-256, candidates SHA-256) — hashes as pinned in 2026-10-22-followup-analyses.md
    ("main (7B, template A)", 1, "redo/rq-c-s42-ollama-t30-r5",
     "d7532c6f81dc3435f752e5a60f360e97a6d12fd29ade5eb2fcbd55a9bd8b6dae",
     "bbd6e0b8f95976fff16bc7c35302d10d97854c94b564c504e2f498e2e02371a0"),
    ("second family (llama3.1:8b)", 2, "family-gpu/rq-c-s42-ollama-t30-r5",
     "56e40a5e54d6a3bbe2884d25bf5e6049d2dd4ecb5c338a177764d709766b4121",
     "9f53d82b6e38ff5286fc62c062cc54579d7a6e8fa9a1b1232f84bea486ce4d61"),
    ("prompt template A (7B)", 2, "template-gpu/A/rq-c-s42-ollama-t30-r5",
     "73dfd090ff3410f1a24e62ff75ab69b0bab90a01fbedfe502ad285f7b6b18436",
     "928a99838f7b57696c2e7fe4731bc3b2890b16c2ed7ef9461d1ad3dae61d2ae3"),
    ("prompt template B (7B)", 2, "template-gpu/B/rq-c-s42-ollama-t30-r5",
     "fc76a3cc69ed351108052c68772902a03b936aa728c28542a0de3ad74c7b07c0",
     "fd4b5408eb2592a9322728e23b51ad669f82bbdcdc8d7b5365636a3ef9439be2"),
]
LOGS = ["run-family-gpu.log", "run-template.log"]
DETERMINISM = ["family-gpu/determinism-llama3.1-8b.json", "family-gpu/determinism-llama3.1-8b-repeat.json",
               "family-gpu/determinism-llama3.1-8b-fixedseed.json", "template-gpu/determinism-7b-fixedseed.json"]
LOG_PATTERN = re.compile(r"error|exception|timeout|fatal|unreachable|retry|stopped|resum", re.IGNORECASE)
P2_MODELS = {"main (7B, template A)": "main (7B)", "prompt template A (7B)": "prompt template A (7B, GPU host)"}

NODE_PARSE = r"""
const vm = require('vm');
let src = '';
process.stdin.on('data', d => src += d);
process.stdin.on('end', () => {
  const out = JSON.parse(src).map(code => {
    try { new vm.Script(code); return true; } catch (e) { return false; }
  });
  process.stdout.write(JSON.stringify(out));
});
"""


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def damaged(text):
    """Kinds of damaged characters in a text: replacement character, control characters, unpaired surrogates."""
    kinds = set()
    for c in text:
        o = ord(c)
        if o == 0xFFFD:
            kinds.add("U+FFFD")
        elif (o < 0x20 and c not in "\t\n\r") or 0x7F <= o <= 0x9F:
            kinds.add("control")
        elif 0xD800 <= o <= 0xDFFF:
            kinds.add("surrogate")
    return sorted(kinds)


def wilson(k, n, z=1.959963984540054):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [max(0.0, c - h), min(1.0, c + h)]


def share(k, n):
    return {"count": k, "of": n, "share": (k / n) if n else None, "wilson95": wilson(k, n)}


def parses(codes):
    if not codes:
        return []
    r = subprocess.run(["node", "-e", NODE_PARSE], input=json.dumps(codes), capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def audit_run(label, host, directory, want_trials, want_cands):
    base = os.path.join(RQC, directory)
    hashes = {}
    for name, want in (("trials.jsonl", want_trials), ("candidates.jsonl", want_cands)):
        got = sha256(os.path.join(base, name))
        if got != want:
            sys.exit(f"{label}: {name} SHA-256 {got} does not match the pinned {want}")
        hashes[name] = got
    rows = [json.loads(line) for line in open(os.path.join(base, "candidates.jsonl"), encoding="utf-8")]
    live = [r for r in rows if not r["reused"]]
    replies = [(r["step"], r.get("selfReply") if r.get("selfReply") is not None else r.get("selfRationale"))
               for r in rows]
    replies = [(s, t) for s, t in replies if t is not None]

    hits = []
    for r in live:
        k = damaged(r.get("generation") or "")
        if k:
            hits.append({"step": r["step"], "field": "generation", "kinds": k, "excerpt": (r.get("generation") or "")[:200]})
    for s, t in replies:
        k = damaged(t)
        if k:
            hits.append({"step": s, "field": "verifierReply", "kinds": k, "excerpt": t[:200]})

    codes = [r.get("code") or "" for r in live]
    nonempty = [c for c in codes if c.strip()]
    ok = parses(nonempty)
    bad_format = [s for s, t in replies if not (t.lstrip().startswith("PASS") or t.lstrip().startswith("FAIL"))]
    return {
        "label": label, "host": host, "directory": f"{RQC}/{directory}", "inputSha256": hashes,
        "liveGenerations": len(live), "verifierReplies": len(replies),
        "A1_damagedTexts": {"generations": sum(1 for h in hits if h["field"] == "generation"),
                            "verifierReplies": sum(1 for h in hits if h["field"] == "verifierReply"), "hits": hits},
        "A2_emptyCode": share(sum(1 for c in codes if not c.strip()), len(codes)),
        "A3_unparsableCode": share(sum(1 for x in ok if not x), len(nonempty)),
        "A4_badVerdictFormat": {**share(len(bad_format), len(replies)), "steps": bad_format[:50]},
    }


def overlap(a, b):
    return a is not None and b is not None and a[0] <= b[1] and b[0] <= a[1]


def git(*args):
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if not os.path.isfile(PLAN):
        sys.exit("run from the repository root")

    runs = [audit_run(*r) for r in RUNS]
    by = {r["label"]: r for r in runs}

    log_lines = []
    for name in LOGS:
        for i, line in enumerate(open(os.path.join(RQC, name), encoding="utf-8", errors="replace"), 1):
            if LOG_PATTERN.search(line):
                log_lines.append({"log": f"{RQC}/{name}", "line": i, "text": line.rstrip()[:300]})

    determinism = []
    for name in DETERMINISM:
        d = json.load(open(os.path.join(RQC, name), encoding="utf-8"))
        determinism.append({"file": f"{RQC}/{name}", "model": d.get("model"), "verdict": d.get("verdict"),
                            "reason": d.get("reason"), "sha256": sha256(os.path.join(RQC, name))})

    p2m = json.load(open(os.path.join(RQC, "p2-models.json"), encoding="utf-8"))
    rates = {}
    for label, key in P2_MODELS.items():
        dg = p2m[key]["diagnostics"]
        rates[label] = {m: {f: dg[m][f] for f in ("numerator", "denominator", "estimate", "wilson95", "taskBootstrapBca95")}
                        for m in ("hallucinationRate", "missRate")}
    h1, h2 = by["main (7B, template A)"], by["prompt template A (7B)"]
    pair = {
        "host1": h1["label"], "host2": h2["label"],
        "intervalsOverlap": {m: overlap(h1[m]["wilson95"], h2[m]["wilson95"])
                             for m in ("A2_emptyCode", "A3_unparsableCode", "A4_badVerdictFormat")},
        "verifierErrorRates": rates,
    }

    host1_kinds = {k for h in h1["A1_damagedTexts"]["hits"] for k in h["kinds"]}
    host2_new = [dict(h, run=r["label"]) for r in runs if r["host"] == 2 for h in r["A1_damagedTexts"]["hits"]
                 if not set(h["kinds"]) <= host1_kinds]
    reasons = []
    if host2_new:
        reasons.append(f"A1: {len(host2_new)} host-2 texts with damaged characters of a kind not seen on host 1")
    for m, ok in pair["intervalsOverlap"].items():
        if not ok:
            reasons.append(f"A7: {m} intervals of the 7B pair do not overlap")
    result = {
        "experiment": "Integrity audit of the RQ-C runs generated on the second host (no model calls)",
        "plan": PLAN, "planCommit": git("log", "-1", "--format=%H", "--", PLAN),
        "codeCommit": os.environ.get("AIJADE_GIT_COMMIT") or git("rev-parse", "HEAD"),
        "codeTreeDirty": bool(git("status", "--porcelain", "--", "experiments/rq-c/host_audit.py")),
        "deviations": [],
        "runs": runs,
        "A5_logLines": log_lines,
        "A6_determinism": determinism,
        "A7_sameModelTwoHosts": pair,
        "reading": {
            "anomaly": bool(reasons), "reasons": reasons,
            "A5": "each listed line is to be matched against the recorded, explained interruptions (see the logs); "
                  "an unexplained error counts as an anomaly",
            "limits": "detects gross corruption only; a change that leaves well-formed text needs a re-run on another host",
        },
        "runtime": {"python": sys.version.split()[0],
                    "node": subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip()},
    }
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    for r in runs:
        print(r["label"], "| live", r["liveGenerations"], "| replies", r["verifierReplies"],
              "| A1", r["A1_damagedTexts"]["generations"], r["A1_damagedTexts"]["verifierReplies"],
              "| A2", r["A2_emptyCode"]["count"], "| A3", r["A3_unparsableCode"]["count"], "/", r["A3_unparsableCode"]["of"],
              "| A4", r["A4_badVerdictFormat"]["count"], "/", r["A4_badVerdictFormat"]["of"])
    print("A5 lines:", len(log_lines))
    for line in log_lines:
        print("  ", line["log"].split("/")[-1], line["line"], line["text"][:150])
    print("A6:", [(d["model"], d["verdict"]) for d in determinism])
    print("A7 overlap:", pair["intervalsOverlap"])
    print("reading:", result["reading"]["anomaly"], reasons)


if __name__ == "__main__":
    main()
