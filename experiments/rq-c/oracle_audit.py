#!/usr/bin/env python3
"""Test-failing candidates against their task instructions: a re-tally of recorded RQ-C runs (4 November 2026).

EXPLORATORY AND AFTER THE FACT. No plan preceded this analysis: the question arose while the first author's manuscript was
being checked, after every result of these runs was known, and the two re-scoring rules below were chosen after reading the
failing candidates. It is a sensitivity analysis of the recorded runs, not a correction of them: the sandbox, the bench and
the runs are unchanged, and the run's own labels stay the reported estimates.

The differential test (`aijade-experiments differential`) asks whether a test-PASSING candidate violates its instruction. This
script asks the reverse: does a test-FAILING candidate satisfy it? It reads only recorded files and makes no model calls. The
recorded programs are replayed in Node's vm under a mirror of the sandbox's rule (src/Aijade.Research/SkillBench/Sandbox.cs);
a program that names a host facility is not replayed and keeps its recorded label. Run labels are checked first: with the
recorded labels the script must reproduce p2-models.json (counts and bootstrap intervals, including its random stream), and
every replayed judged program must agree with its recorded label; otherwise it stops.

Re-scoring rules (the second is a reading of one test case, recorded in TEST_AUDIT):
  entry  A program the sandbox finds no callable in is called through its single top-level `const`/`let`-bound function.
         The generation prompt asks for a function named `solve`, the verifier's prompt does not mention that name, and the
         sandbox's "single user-defined global function" rule does not see lexical bindings.
  test   One test case whose expected output the instruction does not determine is dropped.

A program that passes under a rule counts as usable at every step of the skills that hold it. These are re-labels of the
recorded path: with such a program counted as usable, the feedback loop of the run would have taken another path, so the
re-scored factor counts below describe recorded skills and are not what a corrected run would give. No model is re-fitted.

  usage (from the repository root): python3 -I experiments/rq-c/oracle_audit.py [--out experiments/rq-c/oracle-audit.json]
"""
import argparse
import hashlib
import json
import math
import os
import subprocess
import sys

RQC = "experiments/rq-c"
BENCH = "src/Aijade.Research/SkillBench/bench-data.json"
BENCH_SHA256 = "2a2873e44499418a9cb6031862547ea70bf1722128e0ba6d10a6ad3f38aa85d6"
RUNS = [  # (label in p2-models.json, slug, directory, trials SHA-256, candidates SHA-256)
    ("main (7B)", "main", "redo/rq-c-s42-ollama-t30-r5",
     "d7532c6f81dc3435f752e5a60f360e97a6d12fd29ade5eb2fcbd55a9bd8b6dae",
     "bbd6e0b8f95976fff16bc7c35302d10d97854c94b564c504e2f498e2e02371a0"),
    ("second family (llama3.1:8b)", "fam", "family-gpu/rq-c-s42-ollama-t30-r5",
     "56e40a5e54d6a3bbe2884d25bf5e6049d2dd4ecb5c338a177764d709766b4121",
     "9f53d82b6e38ff5286fc62c062cc54579d7a6e8fa9a1b1232f84bea486ce4d61"),
    ("prompt template A (7B, GPU host)", "tplA", "template-gpu/A/rq-c-s42-ollama-t30-r5",
     "73dfd090ff3410f1a24e62ff75ab69b0bab90a01fbedfe502ad285f7b6b18436",
     "928a99838f7b57696c2e7fe4731bc3b2890b16c2ed7ef9461d1ad3dae61d2ae3"),
    ("prompt template B (7B, GPU host)", "tplB", "template-gpu/B/rq-c-s42-ollama-t30-r5",
     "fc76a3cc69ed351108052c68772902a03b936aa728c28542a0de3ad74c7b07c0",
     "fd4b5408eb2592a9322728e23b51ad669f82bbdcdc8d7b5365636a3ef9439be2"),
    ("second model (1.5B)", "m15", "rq-c-s42-ollama-t30-r5",
     "812a792bdae4362341e19ccd5a8e22e3eb7ffe90a0d160df4275ed60130327ef",
     "d5920b56cf74373eb08b875bebde8e59966a06949fab67ca9da9d998d4b1becc"),
]
DROPPED = {"str-to-camel": ['["Hello-World"]']}
TEST_AUDIT = {
    "casesRead": 228,
    "tasks": 44,
    "reader": "the first author's judgment: one reader, after the results were known",
    "notDeterminedByInstruction": [
        {"task": "str-to-camel", "args": '["Hello-World"]', "expected": '"HelloWorld"',
         "instruction": "converts a kebab-case or snake-case identifier to camelCase (the first word stays lowercase; each following word is capitalized)",
         "reading": "The input is neither kebab-case nor snake-case as the other cases are, and the instruction does not say what happens to an upper-case first word; the expected output, taken from the reference solution, is not camelCase. A program that lower-cases the first word is consistent with the instruction."},
    ],
    "conventionDependent": [
        {"task": "math-round-to", "args": "[-1.5,0]", "expected": "-1", "reading": "'round-half-up' read as toward positive infinity"},
        {"task": "parse-csv-line", "args": '[""]', "expected": '[""]', "reading": "an empty line read as one empty field"},
    ],
}
FEEDBACK_TEXT = "no callable function found (tried `solve`, single global function, and whole-code expression)"

NODE_REPLAY = r"""
const vm = require('vm');
const RISKY = /\b(require|process|import|constructor|globalThis|Function|eval)\b/;
const LEX = /^(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=/gm;
const SUFFIX = `\n;globalThis.__C = (function(){ if (typeof solve !== 'undefined' && typeof solve === 'function') return solve; var fns=[]; var keys=Object.getOwnPropertyNames(globalThis); for (var i=0;i<keys.length;i++){ var k=keys[i]; if (__I.indexOf(k)>=0||k==='__I'||k==='console'||k==='__C') continue; var v; try{v=globalThis[k]}catch(e){continue} if (typeof v==='function') fns.push(v);} return fns.length===1?fns[0]:undefined; })();`;
function newContext() {
  const ctx = vm.createContext({ console: { log() {}, info() {}, warn() {}, error() {}, debug() {}, trace() {} } });
  ctx.__I = vm.runInContext("Object.getOwnPropertyNames(globalThis).filter(function(k){try{return typeof globalThis[k]==='function'}catch(e){return false}})", ctx);
  return ctx;
}
function deepEqual(a, b) {   // Sandbox.DeepEqual: structural, NaN equals NaN, null against an object throws
  if (typeof a === 'number' && typeof b === 'number' && a !== a && b !== b) return true;
  if (a === b) return true;
  if (typeof a !== typeof b) return false;
  if (typeof a !== 'object') return false;
  const A = Array.isArray(a), B = Array.isArray(b);
  if (A || B) {
    if (!A || !B || a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) if (!deepEqual(a[i], b[i])) return false;
    return true;
  }
  if (a === null || b === null) throw new Error('Cannot convert undefined or null to object');
  const ka = Object.keys(a), kb = Object.keys(b);
  if (ka.length !== kb.length) return false;
  for (const k of ka) { if (!Object.hasOwn(b, k)) return false; if (!deepEqual(a[k], b[k])) return false; }
  return true;
}
function resolve(code, timeout, lexical) {
  const ctx = newContext();
  try { vm.runInContext(code + SUFFIX, ctx, { timeout }); } catch (e) { return { via: null, error: String(e).slice(0, 120) }; }
  if (typeof ctx.__C === 'function') return { via: 'sandbox', ctx };
  try {
    const c2 = newContext();
    const v = vm.runInContext('(' + code + ')', c2, { timeout });
    if (typeof v === 'function') { c2.__C = v; return { via: 'sandbox', ctx: c2 }; }
  } catch (e) { /* not an expression */ }
  if (lexical) {
    const fns = [...new Set([...code.matchAll(LEX)].map(m => m[1]))].filter(n => vm.runInContext(`typeof ${n} === 'function'`, ctx));
    if (fns.length === 1) { ctx.__C = vm.runInContext(fns[0], ctx); return { via: 'lexical', ctx }; }
  }
  return { via: null, error: 'no callable' };
}
function run(code, task, lexical, drop) {
  const timeout = task.timeoutMs ?? 2000;
  const r = resolve(code, timeout, lexical);
  if (!r.ctx) return { ok: false, via: null, failing: [], error: r.error };
  const failing = [];
  for (const c of task.tests) {
    if (drop.includes(c.args)) continue;
    try {
      r.ctx.__A = vm.runInContext('(' + c.args + ')', r.ctx);
      const got = vm.runInContext('__C.apply(null, __A)', r.ctx, { timeout });
      const want = vm.runInContext('(' + c.expected + ')', r.ctx);
      if (!deepEqual(got, want)) failing.push({ args: c.args, expected: c.expected, actual: got === undefined ? 'undefined' : JSON.stringify(got) });
    } catch (e) {
      if (String(e).includes('Script execution timed out')) return { ok: false, via: r.via, failing, error: 'timeout' };
      failing.push({ args: c.args, expected: c.expected, threw: String(e).slice(0, 90) });
    }
  }
  return { ok: failing.length === 0, via: r.via, failing };
}
let src = '';
process.stdin.on('data', d => src += d);
process.stdin.on('end', () => {
  const { tasks, pairs, dropped } = JSON.parse(src);
  const out = pairs.map(([id, code]) => {
    if (RISKY.test(code)) return { skipped: true };
    const task = tasks[id];
    return { asRun: run(code, task, false, []), entry: run(code, task, true, []), entryAndTest: run(code, task, true, dropped[id] ?? []) };
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


class NetRandom:
    """System.Random with an explicit seed (.NET's compatibility algorithm), so that the recorded intervals can be reproduced."""
    MAX = 2147483647

    @staticmethod
    def _wrap(v):
        return ((v + 2147483648) % 4294967296) - 2147483648

    def __init__(self, seed):
        a = [0] * 56
        mj = self._wrap(161803398 - abs(seed))
        a[55] = mj
        mk, ii = 1, 0
        for _ in range(1, 55):
            ii += 21
            if ii >= 55:
                ii -= 55
            a[ii] = mk
            mk = self._wrap(mj - mk)
            if mk < 0:
                mk += self.MAX
            mj = a[ii]
        for _ in range(1, 5):
            for i in range(1, 56):
                n = i + 30
                if n >= 55:
                    n -= 55
                a[i] = self._wrap(a[i] - a[1 + n])
                if a[i] < 0:
                    a[i] += self.MAX
        self.a, self.inext, self.inextp = a, 0, 21

    def next(self, n):
        self.inext = 1 if self.inext + 1 >= 56 else self.inext + 1
        self.inextp = 1 if self.inextp + 1 >= 56 else self.inextp + 1
        v = self._wrap(self.a[self.inext] - self.a[self.inextp])
        if v == self.MAX:
            v -= 1
        if v < 0:
            v += self.MAX
        self.a[self.inext] = v
        return int(v * (1.0 / self.MAX) * n)


def horner(c, x):
    r = c[0]
    for v in c[1:]:
        r = r * x + v
    return r


def normal_quantile(p):  # Stats.NormalQuantile
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    plow = 0.02425
    if p <= 0:
        return -math.inf
    if p >= 1:
        return math.inf
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return horner(c, q) / (horner(d, q) * q + 1)
    if p <= 1 - plow:
        q = p - 0.5
        r = q * q
        return horner(a, r) * q / (horner(b, r) * r + 1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -horner(c, q) / (horner(d, q) * q + 1)


def erf(x):  # Stats.Erf (Abramowitz & Stegun 7.1.26)
    ax = abs(x)
    t = 1 / (1 + 0.3275911 * ax)
    y = 1 - horner([1.061405429, -1.453152027, 1.421413741, -0.284496736, 0.254829592], t) * t * math.exp(-ax * ax)
    return -y if x < 0 else y


def normal_cdf(x):
    return 0.5 * (1 + erf(x / math.sqrt(2)))


def wilson(k, n, z=1.959963984540054):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4.0 * n * n)) / d
    return [c - h, c + h]


def bca(s, est, jack, level=0.95):  # RqcModels.Bca
    if len(s) < 100 or len(jack) < 3 or not math.isfinite(est):
        return None
    b = len(s)
    below = (sum(1 for x in s if x < est) + 0.5 * sum(1 for x in s if x == est)) / b
    z0 = normal_quantile(min(max(below, 0.5 / b), 1 - 0.5 / b))
    mean = sum(jack) / len(jack)
    num = sum((mean - j) ** 3 for j in jack)
    den = sum((mean - j) ** 2 for j in jack)
    a = num / (6 * den ** 1.5) if den > 0 else 0

    def at(alpha):
        z = normal_quantile(alpha)
        q = normal_cdf(z0 + (z0 + z) / (1 - a * (z0 + z)))
        pos = min(max(q, 0), 1) * (b - 1)
        lo = math.floor(pos)
        hi = min(b - 1, lo + 1)
        return s[lo] + (s[hi] - s[lo]) * (pos - lo)
    return [at((1 - level) / 2), at((1 + level) / 2)]


def ratio(n, d):
    return n / d if d > 0 else None


STATS = [("hallucinationRate", lambda c: c[1], lambda c: c[1] + c[3]),
         ("missRate", lambda c: c[2], lambda c: c[2] + c[0]),
         ("agreement", lambda c: c[0] + c[3], lambda c: sum(c)),
         ("falseDiscoveryRate", lambda c: c[1], lambda c: c[1] + c[0]),
         ("falseOmissionRate", lambda c: c[2], lambda c: c[2] + c[3])]


def diff_of(c):
    m, h = ratio(STATS[1][1](c), STATS[1][2](c)), ratio(STATS[0][1](c), STATS[0][2](c))
    return m - h if m is not None and h is not None else None


def diagnostics(judged, iterations=10000, seed=0x2545F491):  # RqcModels.Diagnostics; judged is [(task, pass, ok)] in log order
    def add(a, b):
        return (a[0] + b[0], a[1] + b[1], a[2] + b[2], a[3] + b[3])

    def sub(a, b):
        return (a[0] - b[0], a[1] - b[1], a[2] - b[2], a[3] - b[3])
    by, order = {}, []
    for t, p, o in judged:
        if t not in by:
            by[t] = (0, 0, 0, 0)
            order.append(t)
        by[t] = add(by[t], (1 if p and o else 0, 1 if p and not o else 0, 1 if o and not p else 0, 1 if not p and not o else 0))
    tasks = [by[t] for t in order]
    total = (0, 0, 0, 0)
    for c in tasks:
        total = add(total, c)
    boot = [[] for _ in range(len(STATS) + 1)]
    rng = NetRandom(seed)
    for _ in range(iterations):
        s = (0, 0, 0, 0)
        for _k in range(len(tasks)):
            s = add(s, tasks[rng.next(len(tasks))])
        for i, (_n, nu, de) in enumerate(STATS):
            r = ratio(nu(s), de(s))
            if r is not None:
                boot[i].append(r)
        d = diff_of(s)
        if d is not None:
            boot[len(STATS)].append(d)
    jack = [[] for _ in range(len(STATS) + 1)]
    for c in tasks:
        rest = sub(total, c)
        for i, (_n, nu, de) in enumerate(STATS):
            r = ratio(nu(rest), de(rest))
            if r is not None:
                jack[i].append(r)
        d = diff_of(rest)
        if d is not None:
            jack[len(STATS)].append(d)
    out = {"n": sum(total), "tasks": len(tasks), "confusion": dict(zip(("tp", "fp", "fn", "tn"), total)),
           "usableShare": (total[0] + total[2]) / sum(total)}
    for i, (name, nu, de) in enumerate(STATS):
        n, d = nu(total), de(total)
        b = sorted(boot[i])
        o = {"numerator": n, "denominator": d, "estimate": n / d if d else None}
        if d:
            o["wilson95"] = wilson(n, d)
        if b:
            o["taskBootstrap95"] = [b[int(0.025 * (len(b) - 1))], b[math.ceil(0.975 * (len(b) - 1))]]
        if d and bca(b, n / d, jack[i]):
            o["taskBootstrapBca95"] = bca(b, n / d, jack[i])
        out[name] = o
    b = sorted(boot[len(STATS)])
    est = diff_of(total)
    if est is not None and b:
        out["missMinusHallucination"] = {"estimate": est, "taskBootstrap95": [b[int(0.025 * (len(b) - 1))], b[math.ceil(0.975 * (len(b) - 1))]],
                                         "shareOfResamplesAboveZero": sum(1 for x in b if x > 0) / len(b)}
        ci = bca(b, est, jack[len(STATS)])
        if ci:
            out["missMinusHallucination"]["taskBootstrapBca95"] = ci
    return out


def clustered_mcnemar(skills, success):  # RqcModels.ClusteredMcNemar; the last skill of each slot on each side
    pairs = {}
    for s in skills:
        key = (s["sv"], s["trial"], s["task"])
        e = pairs.get(key, (None, None))
        pairs[key] = (e[0], s) if s["ef"] else (s, e[1])
    per, n, b, c = {}, 0, 0, 0
    for (_sv, _trial, task), (off, on) in pairs.items():
        if off is None or on is None:
            continue
        n += 1
        if not success(off) and success(on):
            b += 1
            e = per.get(task, (0, 0))
            per[task] = (e[0] + 1, e[1])
        elif success(off) and not success(on):
            c += 1
            e = per.get(task, (0, 0))
            per[task] = (e[0], e[1] + 1)
    num = sum(v[0] - v[1] for v in per.values())
    den = sum((v[0] - v[1]) ** 2 for v in per.values())
    x2 = num * num / den if den > 0 else None
    return {"pairs": n, "b": b, "c": c, "tasksWithDiscordantPairs": len(per),
            "largestTaskShareOfDiscordant": max(v[0] + v[1] for v in per.values()) / (b + c) if b + c else None,
            "clusteredChiSquare": x2, "clusteredP": math.erfc(math.sqrt(x2) / math.sqrt(2)) if x2 is not None else None,
            "perTask": {k: {"b": v[0], "c": v[1]} for k, v in sorted(per.items())}}


def close(a, b, tol=1e-9):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol


def audit_run(label, slug, directory, want_t, want_c, tasks, models):
    base = os.path.join(RQC, directory)
    for name, want in (("trials.jsonl", want_t), ("candidates.jsonl", want_c)):
        if sha256(os.path.join(base, name)) != want:
            sys.exit(f"{label}: {name} does not match its pinned SHA-256")
    trials = [json.loads(line) for line in open(os.path.join(base, "trials.jsonl"), encoding="utf-8")]
    cands = [json.loads(line) for line in open(os.path.join(base, "candidates.jsonl"), encoding="utf-8")]
    if len(trials) != len(cands) or any(a["skillId"] != b["skillId"] for a, b in zip(trials, cands)):
        sys.exit(f"{label}: trials and candidates are not aligned")
    skills, by_id = [], {}
    for t, c in zip(trials, cands):
        s = by_id.get(t["skillId"])
        if s is None:
            s = {"id": t["skillId"], "sv": t["condition"].startswith("sv1"), "ef": t["condition"].endswith("ef1"), "cell": t["condition"],
                 "trial": t["trial"], "task": t["taskId"], "verdict": t["selfVerdict"], "code": c["code"], "calls": 0, "succ": 0, "last": None}
            by_id[t["skillId"]] = s
            skills.append(s)
        s["calls"] += 1
        s["succ"] += 1 if t["execOk"] else 0
        s["last"] = t["execOk"]
    pairs = sorted({(s["task"], s["code"]) for s in skills if s["code"] is not None})
    r = subprocess.run(["node", "-e", NODE_REPLAY], input=json.dumps({"tasks": tasks, "pairs": pairs, "dropped": DROPPED}),
                       capture_output=True, text=True, check=True)
    replay = dict(zip(pairs, json.loads(r.stdout)))

    def rule_ok(s, rule):
        v = replay.get((s["task"], s["code"]))
        return bool(v and not v.get("skipped") and v[rule]["ok"])

    def judged_list(rule):
        out = []
        for s in skills:
            if s["verdict"] is None or s["last"] is None:
                continue
            out.append((s["task"], s["verdict"] == "pass", s["last"] or (rule is not None and rule_ok(s, rule))))
        return out

    def success(rule):
        def f(s):
            return (rule is not None and rule_ok(s, rule)) or (s["calls"] > 0 and s["succ"] / s["calls"] >= 0.5)
        return f

    def distinct(rule):
        seen = {}
        for s in skills:
            if s["verdict"] is None or s["last"] is None:
                continue
            k = (s["task"], s["code"])
            if k not in seen:   # a candidate is counted once, by its first generation
                seen[k] = (s["verdict"] == "pass", s["last"] or (rule is not None and rule_ok(s, rule)))
        unusable = [k for k, v in seen.items() if not v[1]]
        fp = [k for k in unusable if seen[k][0]]
        return {"candidates": len(seen), "unusable": len(unusable), "unusableTasks": len({k[0] for k in unusable}),
                "falsePasses": len(fp), "falsePassTasks": len({k[0] for k in fp})}

    def informative(rule):
        ok = success(rule)
        seen = {}
        for s in skills:
            seen.setdefault(s["task"], set()).add(ok(s))
        return sorted(t for t, v in seen.items() if len(v) == 2)

    labels = {}
    for name, rule in (("asRun", None), ("entry", "entry"), ("entryAndTest", "entryAndTest")):
        labels[name] = {"diagnostics": diagnostics(judged_list(rule)), "distinct": distinct(rule),
                        "clusteredMcNemar": clustered_mcnemar(skills, success(rule)), "informativeTasks": informative(rule)}

    # Checks: the recorded labels must reproduce the archived analysis, and the replay must agree with the recorded labels.
    arch = models[label]
    checks = []
    a, m = labels["asRun"]["diagnostics"], arch["diagnostics"]
    checks.append(a["confusion"] == m["confusion"])
    for name in ("hallucinationRate", "missRate", "falseDiscoveryRate", "falseOmissionRate"):
        for f in ("taskBootstrap95", "taskBootstrapBca95"):
            if f in m[name]:
                checks.extend(close(x, y) for x, y in zip(a[name].get(f, [None, None]), m[name][f]))
    q, w = labels["asRun"]["clusteredMcNemar"], arch["clusteredMcNemar"]
    checks.extend(q[k] == w[k] for k in ("pairs", "b", "c", "tasksWithDiscordantPairs"))
    checks.append(close(q["clusteredP"], w["clusteredP"]))
    checks.append(len(labels["asRun"]["informativeTasks"]) == arch["conditionalLogistic"].get("informativeStrata"))
    if not all(checks):
        sys.exit(f"{label}: the recorded labels do not reproduce p2-models.json")
    judged = [s for s in skills if s["verdict"] is not None]
    skipped = sum(1 for v in replay.values() if v.get("skipped"))
    disagree_judged = [s["id"] for s in judged if not replay[(s["task"], s["code"])].get("skipped")
                       and replay[(s["task"], s["code"])]["asRun"]["ok"] != s["last"]]
    disagree_all = [s["id"] for s in skills if s["code"] is not None and not replay[(s["task"], s["code"])].get("skipped")
                    and replay[(s["task"], s["code"])]["asRun"]["ok"] != s["last"]]
    if disagree_judged:
        sys.exit(f"{label}: replay disagrees with the recorded label on judged skills {disagree_judged[:5]}")

    def members(rule_new, rule_old):
        out = []
        for (task, code), v in sorted(replay.items()):
            if v.get("skipped"):
                continue
            was = v[rule_old]["ok"] if rule_old else v["asRun"]["ok"]
            if v[rule_new]["ok"] and not was:
                held = [s for s in skills if s["task"] == task and s["code"] == code]
                j = [s for s in held if s["verdict"] is not None]
                out.append({"task": task, "code": code, "skills": len(held), "judgedSkills": len(j),
                            "verifierPassed": sum(1 for s in j if s["verdict"] == "pass"),
                            "failingAsRun": v["asRun"]["failing"], "errorAsRun": v["asRun"].get("error")})
        return out
    entry, test = members("entry", None), members("entryAndTest", "entry")
    sole = {}
    for s in judged:
        v = replay[(s["task"], s["code"])]
        if not v.get("skipped") and not v["asRun"]["ok"] and len(v["asRun"]["failing"]) == 1:
            k = s["task"] + " " + v["asRun"]["failing"][0]["args"]
            sole[k] = sole.get(k, 0) + 1
    rec = {"label": label, "slug": slug, "directory": directory, "hashes": {"trials.jsonl": want_t, "candidates.jsonl": want_c},
           "replay": {"distinctPrograms": len(pairs), "notReplayed": skipped, "disagreementsOnJudgedSkills": 0,
                      "disagreementsOnAllSkills": len(disagree_all)},
           "entryClass": entry, "testClass": test, "soleFailingCaseOfJudgedSkills": dict(sorted(sole.items())), "labels": labels}
    return rec, skills, replay


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(RQC, "oracle-audit.json"))
    args = ap.parse_args()
    if sha256(BENCH) != BENCH_SHA256:
        sys.exit("the bench does not match its pinned SHA-256")
    bench = json.load(open(BENCH, encoding="utf-8"))
    tasks = {t["id"]: {"tests": t["tests"], "timeoutMs": t.get("timeoutMs")} for t in bench["tasks"]}
    if sum(len(t["tests"]) for t in tasks.values()) != TEST_AUDIT["casesRead"] or len(tasks) != TEST_AUDIT["tasks"]:
        sys.exit("the bench changed since its test cases were read")
    models = json.load(open(os.path.join(RQC, "p2-models.json"), encoding="utf-8"))
    runs, main_skills, main_replay = [], None, None
    for label, slug, directory, want_t, want_c in RUNS:
        rec, skills, replay = audit_run(label, slug, directory, want_t, want_c, tasks, models)
        runs.append(rec)
        if slug == "main":
            main_skills, main_replay = skills, replay

    # The worked example of the paper: the program behind the largest group of false passes that fails on behavior.
    candidates = []
    for (task, code), v in sorted(main_replay.items()):
        held = [s for s in main_skills if s["task"] == task and s["code"] == code and s["verdict"] is not None]
        passed = sum(1 for s in held if s["verdict"] == "pass")
        if passed and not v["asRun"]["ok"] and not v["entryAndTest"]["ok"]:
            candidates.append((passed, task, code, v["asRun"]))
    passed, task, code, res = max(candidates, key=lambda c: c[0])
    bench_task = next(t for t in bench["tasks"] if t["id"] == task)
    example = {"task": task, "instruction": bench_task["instruction"], "code": code, "falsePasses": passed, "cases": len(bench_task["tests"]), "failing": res["failing"]}

    # In the main run, what the feedback changed in the task that contributes most discordant pairs.
    top = max(runs[0]["labels"]["asRun"]["clusteredMcNemar"]["perTask"].items(), key=lambda kv: kv[1]["b"] + kv[1]["c"])[0]
    programs = {}
    for s in main_skills:
        if s["task"] == top:
            p = programs.setdefault(s["code"], {"code": s["code"], "cells": {}, "skills": 0})
            p["skills"] += 1
            p["cells"][s["cell"]] = p["cells"].get(s["cell"], 0) + 1
            p["usable"] = bool(s["last"])
    feedback = {"task": top, "programs": list(programs.values()), "sandboxMessage": FEEDBACK_TEXT}

    audit = dict(TEST_AUDIT)
    audit["judgedSkillsFailingOnlyThisCase"] = {
        f"{c['task']} {c['args']}": {r["slug"]: r["soleFailingCaseOfJudgedSkills"].get(f"{c['task']} {c['args']}", 0) for r in runs}
        for c in TEST_AUDIT["notDeterminedByInstruction"] + TEST_AUDIT["conventionDependent"]}
    result = {
        "experiment": "test-failing candidates against their task instructions: re-tally of recorded RQ-C runs, no model calls",
        "status": "exploratory, after the results were known; no plan preceded it; the run's own labels stay the reported estimates",
        "bench": {"file": BENCH, "sha256": BENCH_SHA256},
        "reproduces": "with the recorded labels: p2-models.json confusion counts, percentile and BCa task-bootstrap intervals, clustered McNemar and informative strata, for every run below",
        "rules": {
            "entry": "a program in which the sandbox finds no callable is called through its single top-level const/let-bound function",
            "test": "the test cases listed under testAudit.notDeterminedByInstruction are dropped",
            "relabeling": "a program that passes under a rule counts as usable at every step of the skills that hold it; the recorded path is kept, so factor counts are not what a corrected run would give; no model is re-fitted",
        },
        "testAudit": audit,
        "runs": runs,
        "example": example,
        "feedbackDetail": feedback,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
        f.write("\n")
    for r in runs:
        d0, d1, d2 = (r["labels"][k]["diagnostics"] for k in ("asRun", "entry", "entryAndTest"))
        print(r["slug"], "programs", r["replay"], "entry", len(r["entryClass"]), "test", len(r["testClass"]))
        for name, d in (("asRun", d0), ("entry", d1), ("entry+test", d2)):
            h, m = d["hallucinationRate"], d["missRate"]
            print(f"  {name:10s} conf {d['confusion']} hal {h['numerator']}/{h['denominator']}={h['estimate']} bca {h.get('taskBootstrapBca95')} miss {m['numerator']}/{m['denominator']}={m['estimate']} bca {m.get('taskBootstrapBca95')}")
    print("written", args.out)


if __name__ == "__main__":
    main()
