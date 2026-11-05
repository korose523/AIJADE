#!/usr/bin/env python3
"""P1-B follow-up (experiments/plans/2026-11-05-p1-b-survivor-reading.md): one reader's categories for the 357 survivors, and the scores with equivalents excluded.

Usage: survivor_reading.py <independent-fault-set.json> <out.json>
"""
import collections
import json
import math
import sys

AWAIT = "ConfigureAwait's flag only picks the synchronization context, and the server and worker have none"
LABEL = "a stage or result label that only logs and callers' messages read"
MESSAGE = "only the text or path of a validation message"
STORED = "changes a field written to a stored row, and the matrix reads no such row"

EQUIVALENT = {
    "PgcGate.cs": {3610: "a vertex of exactly 0 only adds a candidate 0 that the list already holds", 3612: "a vertex of exactly 1 only adds a candidate 1 that the list already holds",
                   3652: "with no evidence ids the strength is 0 or NaN on every path, so the second operand decides anyway",
                   3700: "each entry's id comes from the same candidates, so First always finds one"},
    "PromotionService.cs": {5345: "the input holds exactly one candidate, so the plan always has one entry", 5348: "the input holds exactly one candidate, so the plan always has one entry",
                            5388: AWAIT, 5389: AWAIT, 5393: AWAIT, 5404: AWAIT, 5406: AWAIT},
    "V9EventService.cs": {i: AWAIT for i in (6167, 6169, 6171, 6173, 6177, 6187, 6188, 6190, 6192, 6194, 6200, 6209, 6250, 6306, 6325)},
    "WireSchema.cs": {397: "the initial value is read only when TryString returned false, and no caller reads it then"},
    "V9Endpoints.cs": {5720: AWAIT},
}
DIAGNOSTIC = {
    "PgcGate.cs": {3521: "an expected-test label that is only serialized", 3522: "an expected-test label that is only serialized", 3523: "an expected-test label that is only serialized"},
    "PromotionService.cs": {**{i: LABEL for i in (5337, 5340, 5344, 5363, 5408, 5409)}, 5341: "the text of a refusal reason", 5364: "the text of a refusal reason",
                            5392: "a descriptive name of a stored row", 5395: "a descriptive name of a stored row"},
    "ShadowParams.cs": {4827: "the text of a refusal reason"},
    "Vse.cs": {i: "the text of a refusal reason" for i in (1599, 1602, 1608, 1611, 1614)},
    "V9EventService.cs": {**{i: "the text of an exception or public error message" for i in (6095, 6096, 6097, 6098, 6101, 6247, 6322)}, 6210: "a log call", 6211: "a log message",
                          6237: "a field label used only in an exception message", 6238: "a field label used only in an exception message", 6207: "the actor label of an audit row, which no code reads"},
    "Boundary.cs": {i: MESSAGE for i in (4970, 4989, 5012, 5019, 5045, 5051, 5084, 5085, 5088, 5096, 5097)},
    "WireSchema.cs": {i: MESSAGE for i in (386, 418, 447, 454, 471, 496, 502, 527, 530, 536)},
}
DECISION_BY_FILE = {
    "PgcGate.cs": {122: "changes the default policy's version or evidence rule", 125: "changes the neutral policy's key", 160: "changes a commitment weight's coefficient", 161: "changes a commitment weight's coefficient", 162: "changes a commitment weight's coefficient", 163: "changes a commitment weight's coefficient",
                   168: "changes the high-contradiction rule", 170: "changes the clamp", 180: "drops the candidate's claims from contradiction detection", 184: "drops the beliefs from contradiction detection", 203: "changes contradiction detection on evidence records",
                   240: "changes persona-shift risk", 253: "changes a reason code's wire name in stored plans", 276: "changes the commitment weight", 277: "changes the commitment weight", 278: "changes the commitment weight's clamp",
                   283: "ignores a caller's policy", 284: "changes the contradiction level", 291: "ignores a caller's policy", 292: "changes the contradiction branch", 294: "changes the fatigue branch", 296: "changes the commit branch", 297: "changes the deferred flag", 298: "changes the throttle branch", 300: "changes the deferred flag",
                   310: "ignores a caller's parameters", 315: "changes the upper bound of the weight", 316: "changes the upper bound of the weight", 319: "changes the upper bound of the weight", 320: "changes the upper bound of the weight", 323: "changes which vertices are tried", 325: "changes the vertex", 328: "changes the vertex", 329: "changes which vertices are tried", 336: "changes the upper bound of the weight",
                   343: "ignores a caller's threshold", 344: "changes the commit verdict at the threshold", 352: "changes the commit verdict at the threshold", 361: "drops evidence records from the decision", 367: "changes the stored state id", 375: "changes evidence sufficiency", 432: "drops evidence records from the report", 438: "changes the report's severity", 440: "changes the stored decision id", 441: "changes the contradiction report"},
    "PromotionService.cs": {28: "ignores an injected clock", 61: STORED, 62: STORED, 63: STORED, 64: STORED, 65: STORED, 66: STORED, 86: "changes the commit verdict for a job without a state, or the verdict's source", 87: "changes the stored commit reason", 96: STORED, 97: STORED, 99: STORED, 100: STORED, 101: STORED, 102: STORED, 103: STORED, 104: STORED, 105: STORED, 106: STORED, 107: STORED, 108: STORED, 116: STORED, 117: STORED},
    "ShadowParams.cs": {34: "changes the proposal's stored and queued form", 36: "changes the proposal's stored and queued form", 37: "changes the proposal's stored and queued form", 38: "changes the proposal's stored and queued form", 39: "changes the proposal's stored and queued form", 40: "changes the proposal's stored and queued form", 41: "changes the proposal's stored and queued form", 42: "changes the proposal's stored and queued form",
                        44: "changes which optional fields the form holds", 46: "changes which optional fields the form holds", 48: "changes which optional fields the form holds", 50: "changes which optional fields the form holds", 52: "changes which optional fields the form holds",
                        75: "changes the input hash's value for every proposal", 133: "changes the confidence clamp", 134: "changes the candidate's id, evidence or salience"},
    "Vse.cs": {122: "a failed dependency scan passes, the gap the hand-written mutants also found"},
    "V9EventService.cs": {56: "drops or misreads tick or input hash from the envelope", 57: "drops the core state node", 75: "ignores an injected clock", 79: "changes the stored pairing status", 143: "changes the stored causality", 164: "changes which receipts are checked for pairing", 165: "changes the pairing result", 168: "changes the pairing check", 171: "drops the audit row of a pairing gap", 172: "changes the action that the admin count reads", 175: "changes the pairing result",
                          185: "changes the stored session", 186: "changes the stored snapshot", 190: "drops the asset version from the projection", 191: "changes the stored receipt event", 192: "changes the stored request event", 199: "applies the self-reference rule with the checks off", 240: "weakens the self-reference rule", 242: "removes the self-reference refusal, so another reason or none applies", 245: "throws instead of the not-found refusal"},
    "Boundary.cs": {87: "inverts the literal rule", 88: "changes the numeric literal rule", 108: "array items are not validated", 188: "treats a non-strict object as strict", 200: "a whole-number rule accepts fractions", 259: "refuses a valid replay mode", 260: "refuses a valid risk level", 263: "refuses a valid optional field", 270: "misnames a field of the v10 requirement", 276: "misnames a field of a rule whose fixtures do not reach it", 278: "misnames a field of a rule whose fixtures do not reach it", 282: "misnames a field of a rule whose fixtures do not reach it", 317: "misnames a perception field", 318: "misnames a perception field", 319: "misnames a perception field", 320: "misnames a perception field", 323: "misnames a perception field", 324: "misnames a perception field", 327: "changes which topics need the v10 fields"},
    "WireSchema.cs": {35: "the optional modifier has no effect", 67: "Num rejects fractions", 69: "Whole accepts fractions", 98: "copying drops the optional flag", 107: "a non-number can pass", 112: "changes the whole-number or safe-integer check", 120: "copying drops the optional flag", 127: "a non-string or unlisted value can pass", 131: "copying drops the optional flag", 139: "a wrong literal passes", 171: "array items are not validated", 211: "composition drops fields", 262: "copying drops the optional flag"},
    "V9Endpoints.cs": {22: "an observation topic is not dispatched", 23: "an observation topic is not dispatched", 28: "changes the published reason chain", 51: "removes or breaks an endpoint", 52: "removes or breaks an endpoint", 53: "removes or breaks an endpoint", 54: "removes or breaks an endpoint"},
}


def wilson(k, n, z=1.959964):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0, c - h), 4), round(min(1, c + h), 4)]


def main():
    source, target = sys.argv[1:3]
    d = json.load(open(source, encoding="utf-8"))
    cols = d["mutantColumns"]
    rows = [dict(zip(cols, m)) for m in d["mutants"]]
    out = []
    for r in rows:
        final = r["hand"] or r["tool"]
        if final != "Survived":
            continue
        i, f = int(r["key"].split(":")[1]), r["file"]
        if i in EQUIVALENT.get(f, {}):
            cat, why = "equivalent", EQUIVALENT[f][i]
        elif i in DIAGNOSTIC.get(f, {}):
            cat, why = "diagnostic", DIAGNOSTIC[f][i]
        else:
            cat, why = "decision", DECISION_BY_FILE[f][r["line"]]
        out.append({"key": r["key"], "matrix": "drift" if r["key"].startswith("drift") else "gate", "file": f, "line": r["line"], "mutator": r["mutator"], "category": cat, "reason": why})
    assert len(out) == 357, len(out)
    report = {"experiment": "P1-B follow-up: one reader's categories for the surviving mutants", "plan": "experiments/plans/2026-11-05-p1-b-survivor-reading.md", "reader": "Claude; one reader; the first author has not yet read it", "readAt": "9922825", "matrices": {}, "byFile": {}, "rows": out}
    for m in ("drift", "gate"):
        s = d["byMatrix"][m]
        c = collections.Counter(r["category"] for r in out if r["matrix"] == m)
        k, sv, n = s["killed"], s["survived"], s["noCoverage"]
        e, di = c["equivalent"], c["diagnostic"]
        report["matrices"][m] = {"survivors": sv, **c, "score": s["score"], "executedScore": s["executedScore"],
                                 "scoreWithoutEquivalents": round(k / (k + sv + n - e), 4), "scoreWithoutEquivalentsCi95": wilson(k, k + sv + n - e),
                                 "executedScoreWithoutEquivalents": round(k / (k + sv - e), 4), "executedScoreWithoutEquivalentsCi95": wilson(k, k + sv - e),
                                 "executedScoreOverDecisionsOnly": round(k / (k + c["decision"]), 4), "executedScoreOverDecisionsOnlyCi95": wilson(k, k + c["decision"])}
    for f in sorted({r["file"] for r in out}):
        report["byFile"][f] = dict(collections.Counter(r["category"] for r in out if r["file"] == f))
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(json.dumps({k: report[k] for k in ("matrices", "byFile")}, indent=None))


if __name__ == "__main__":
    main()
