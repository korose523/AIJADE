#!/usr/bin/env python3
"""P3-E: summarize product-path-{text,embedding}.json into product-path.json.

Per question, the share of its evidence turns present at each stage; averaged over the questions of a
conversation, then over the conversations; conversation bootstrap (10,000 resamples, percentile 95%).
Usage: product_path_summary.py <dir with the two row files> <output file>
"""
import json
import random
import sys

STAGES = ["stored", "pool", "above", "response", "kept", "prompt"]


def by_conversation(rows, value):
    groups = {}
    for r in rows:
        v = value(r)
        if v is not None:
            groups.setdefault(r["c"], []).append(v)
    return {c: sum(v) / len(v) for c, v in groups.items()}


def interval(means, seed=20261105, n=10000):
    keys = sorted(means)
    rng = random.Random(seed)
    draws = sorted(sum(means[rng.choice(keys)] for _ in keys) / len(keys) for _ in range(n))
    return [round(draws[int(0.025 * n)], 4), round(draws[int(0.975 * n)], 4)]


def describe(rows, value):
    means = by_conversation(rows, value)
    return {"mean": round(sum(means.values()) / len(means), 4), "ci95": interval(means), "questions": sum(value(r) is not None for r in rows)}


def share(stage, base="evidence"):
    return lambda r: r[stage] / r[base] if r[base] else None


def hit(stage):
    return lambda r: float(r[stage] > 0) if r["evidence"] else None


def diff(a, b):
    return lambda r: (r[a] - r[b]) / r["evidence"] if r["evidence"] else None


def part(rows):
    out = {"questions": len(rows), "noEvidenceListed": sum(not r["evidence"] for r in rows), "evidenceNotLocated": sum(r["located"] < r["evidence"] for r in rows)}
    out["recall"] = {s: describe(rows, share(s)) for s in STAGES}
    out["recallOfLocated"] = {s: describe(rows, share(s, "located")) for s in STAGES}
    out["anyEvidence"] = {s: describe(rows, hit(s)) for s in STAGES}
    out["loss"] = {f"{a}->{b}": describe(rows, diff(a, b)) for a, b in zip(STAGES, STAGES[1:])}
    out["loss"]["pool->prompt"] = describe(rows, diff("pool", "prompt"))
    out["arm"] = {
        "recencyTop5": describe(rows, share("prompt")),
        "serverTop5": describe(rows, share("serverTop5")),
        "serverMinusRecency": describe(rows, diff("serverTop5", "prompt")),
        "anyRecencyTop5": describe(rows, hit("prompt")),
        "anyServerTop5": describe(rows, hit("serverTop5")),
    }
    for key, field in [("newerInPrompt", "newerInPrompt"), ("newerInServerTop5", "newerInServerTop5")]:
        out[key] = describe(rows, lambda r, f=field: float(r[f]) if r[f] is not None else None)
    out["counts"] = {
        "firstSearchEmpty": sum(r["firstEmpty"] for r in rows),
        "termSearches": sum(r["termSearch"] for r in rows),
        "fewerThanFive": sum(r["fewerThanFive"] for r in rows),
        "noneInPrompt": sum(r["promptItems"] == 0 for r in rows),
        "repeatsInPrompt": sum(r["repeatsInPrompt"] for r in rows),
        "echoDropped": sum(r["echoDropped"] for r in rows),
        "responseMismatches": sum(r["mismatch"] for r in rows),
    }
    ms = sorted(r["ms"] for r in rows)
    out["msPerQuestionMedian"] = ms[len(ms) // 2]
    out["callsPerQuestionMean"] = round(sum(r["calls"] for r in rows) / len(rows), 2)
    return out


def main():
    folder, target = sys.argv[1], sys.argv[2]
    report = {"experiment": "P3-E: evidence along the product's delivery path", "plan": "experiments/plans/2026-11-05-p3-e-product-delivery-path.md", "conditions": {}}
    for condition in ["text", "embedding"]:
        try:
            with open(f"{folder}/product-path-{condition}.json", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            continue
        rows = data.pop("rows")
        data["answerable"] = part([r for r in rows if r["answerable"]])
        data["all"] = part(rows)
        report["conditions"][condition] = data
    with open(target, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
