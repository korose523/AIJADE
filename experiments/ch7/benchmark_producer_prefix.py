"""Compare two exact prefix checks on the retained E6 journal.

Run with the original journal, initialization record and cold-audit cutoffs.
This measures a producer component offline. The live Registry is untouched.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import random
import statistics
import sys
import time

import process_lifecycle as lifecycle


SOURCE = "4599cfe9885e529e99ba22f7ffdbfb2ce290d583"
EXPECTED = {
    "journal": "36dcdadc3f09477e69b5ad0eede667b7338d31cc161e3ddf0d46103d88600084",
    "initialization": "635b4655a9b96da8f50a8f45aeba148f14f4b2fb000536205fa83b8abcf2154c",
    "cold_details": "d980e25e6e6cb75dbf8591d49a9d8a517d50caf8c473a34ae1e3b2039426ab2e",
    "producer": "93e12314fd66c4cde97323afcda7c6f7ba3e08a9a9fe078aba6b22845ea12c65",
}
SAMPLES = (0, 83, 166, 167)
PAIRS = 24
SEED = 20261118


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_input(path, kind):
    raw = path.read_bytes()
    require(digest(raw) == EXPECTED[kind], f"{kind} SHA256 differs")
    return raw


def slice_equal(raw, previous):
    return type(raw) is bytes and len(raw) >= len(previous) and raw[:len(previous)] == previous


def startswith(raw, previous):
    return type(raw) is bytes and len(raw) >= len(previous) and raw.startswith(previous)


def elapsed(function, *args):
    start = time.perf_counter_ns()
    result = function(*args)
    return result, time.perf_counter_ns() - start


def stats(values):
    return {"minNs": min(values), "medianNs": statistics.median(values), "maxNs": max(values)}


def paired(raw, previous, rng):
    methods = {"slice": slice_equal, "startswith": startswith}
    first = ["slice", "startswith"] * (PAIRS // 2)
    rng.shuffle(first)
    rows = []
    for initial in first:
        order = [initial, next(name for name in methods if name != initial)]
        row = {"order": order}
        for name in order:
            matches, row[name] = elapsed(methods[name], raw, previous)
            require(matches, f"{name} rejected authentic prefix")
        rows.append(row)
    return {
        "rows": rows,
        "slice": stats([row["slice"] for row in rows]),
        "startswith": stats([row["startswith"] for row in rows]),
        "pairedSliceMinusStartswith": stats([row["slice"] - row["startswith"] for row in rows]),
    }


def typed_equal(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return list(left) == list(right) and all(typed_equal(left[k], right[k]) for k in left)
    if isinstance(left, (list, tuple)):
        return len(left) == len(right) and all(typed_equal(a, b) for a, b in zip(left, right))
    return left == right


def replay_increment(current, previous, cold):
    state = lifecycle.replay_journal(previous)
    tail = current[len(previous):]
    incremental, tail_ns = elapsed(lifecycle.replay_journal, tail, state)
    # The original Registry computes the complete digest from the previous
    # hasher and the new tail, replacing tail-local bytes and digest fields.
    hasher = hashlib.sha256(previous)
    hasher.update(tail)
    incremental.update(bytes=len(current), sha256=hasher.hexdigest())
    require(typed_equal(incremental, cold), "incremental and cold typed state differ")
    return tail_ns


def adverse_controls(previous, current, journal):
    outcomes = {}
    for place, index in (("first", 0), ("middle", len(previous) // 2), ("last", len(previous) - 1)):
        mutated = current[:index] + bytes([current[index] ^ 1]) + current[index + 1:]
        require(not slice_equal(mutated, previous) and not startswith(mutated, previous), place)
        outcomes["edited_" + place] = "BOTH_REJECT"
    for name, raw in (("older_legal_cutoff", journal[:EXPECTED_INITIAL_BYTES]), ("wrong_type", bytearray(current))):
        require(not slice_equal(raw, previous) and not startswith(raw, previous), name)
        outcomes[name] = "BOTH_REJECT"
    # Prefix matching by itself does not authenticate a new event. The shared
    # original parser still has to reject a malformed tail after either check.
    malformed = previous + b"{}\n"
    require(slice_equal(malformed, previous) and startswith(malformed, previous), "malformed control setup")
    try:
        lifecycle.replay_journal(malformed[len(previous):], lifecycle.replay_journal(previous))
    except ValueError:
        outcomes["malformed_new_event"] = "PREFIX_MATCHES_SHARED_PARSER_REJECTS"
    else:
        raise ValueError("invalid journal tail unexpectedly accepted")
    return outcomes


EXPECTED_INITIAL_BYTES = 6_220_382


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("journal", "initialization", "cold-details", "plan", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "choose a new evidence output")
    plan_raw = args.plan.read_bytes()
    plan = json.loads(plan_raw)
    script = Path(__file__)
    require(digest(script.read_bytes()) == plan["benchmarkSha256"], "benchmark differs from written plan")
    require(plan["inputs"] == EXPECTED and plan["pairsPerCondition"] == PAIRS
            and plan["rawIndices"] == list(SAMPLES) and plan["orderSeed"] == SEED, "plan parameters differ")
    verify_input(Path(lifecycle.__file__), "producer")
    journal = verify_input(args.journal, "journal")
    init = json.loads(verify_input(args.initialization, "initialization"))
    audit = json.loads(verify_input(args.cold_details, "cold_details"))
    require(init["sourceCommit"] == audit["sourceCommit"] == SOURCE, "source identity differs")
    rows = audit["samples"]
    require(len(rows) == 168 and [r["globalIndex"] for r in rows] == list(range(168)), "cutoff population differs")
    cutoffs = [{"prefixBytes": init["prefixBytes"], "prefixEvents": init["lastSequence"],
                "prefixSha256": init["prefixSha256"]}, *rows]
    require(cutoffs[0]["prefixBytes"] == EXPECTED_INITIAL_BYTES, "initial size differs")
    last_size = 0
    frontier = hashlib.sha256()
    for row in cutoffs:
        size = row["prefixBytes"]
        require(last_size < size <= len(journal) and journal[size - 1] == 10, "cutoff order/boundary")
        frontier.update(memoryview(journal)[last_size:size])
        require(frontier.hexdigest() == row["prefixSha256"], "cutoff SHA256 differs")
        last_size = size

    measurements = []
    rng = random.Random(SEED)
    started_at = datetime.now(timezone.utc).isoformat()
    for index in SAMPLES:
        prior, now = cutoffs[index:index + 2]
        previous = journal[:prior["prefixBytes"]]
        current = journal[:now["prefixBytes"]]
        same = memoryview(current).tobytes()
        require(same is not current, "equal-length control needs independent read buffers")
        cold, cold_ns = elapsed(lifecycle.replay_journal, current)
        require(cold["lastSequence"] == now["prefixEvents"], "cold sequence differs")
        tail_ns = replay_increment(current, previous, cold)
        measurements.append({
            "rawIndex": index, "priorBytes": len(previous), "currentBytes": len(current),
            "tailBytes": len(current) - len(previous), "currentEvents": now["prefixEvents"],
            "currentPrefixSha256": now["prefixSha256"], "coldReplayNs": cold_ns,
            "tailReplayNs": tail_ns, "typedColdEquivalence": True,
            "append": paired(current, previous, rng),
            "sameLength": paired(current, same, rng),
        })
    controls = adverse_controls(previous, current, journal)
    result = {
        "schema": "aijade.ch7.offline-producer-prefix-comparison.v1",
        "status": "OFFLINE_COMPONENT_MEASURED",
        "startedAt": started_at, "completedAt": datetime.now(timezone.utc).isoformat(),
        "planSha256": digest(plan_raw), "benchmarkSha256": digest(script.read_bytes()),
        "inputs": EXPECTED, "sourceCommit": SOURCE, "python": sys.version,
        "platform": platform.platform(), "cutoffsVerified": len(cutoffs),
        "comparisonCalls": len(SAMPLES) * PAIRS * 4, "measurements": measurements, "controls": controls,
        "runningBoundary": "In-memory exact prefix comparison. Read, fsync, native collection, full callback and real concurrency were outside the timed comparison.",
        "backendQualification": "NOT_RUN", "heldoutComparison": "NOT_RUN",
    }
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(f"{result['status']}: {len(cutoffs)} cutoffs, {result['comparisonCalls']} timed comparisons")


if __name__ == "__main__":
    main()
