"""Summarize paired LangChain access-refresh transitions from the frozen policy archive."""

import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean

from analyze import observed


ROOT = Path(__file__).resolve().parent
EXTERNAL = Path("runs/attempt-03/external/langchain")
JOURNAL = EXTERNAL / "langchain.jsonl.gz"
CAPTURES = EXTERNAL / "langchain-prompts.jsonl.gz"
CAPTURE_RECEIPT = EXTERNAL / "langchain-prompts.jsonl.gz.receipt.json"
NATIVE_RECEIPT = EXTERNAL / "receipt.json"
CORPUS = Path("corpus-export.json.gz")
SUMMARY = Path("summary.json")
ORIGINAL_RECEIPT_SHA = "14c2ccb758be03998f117dcec93e5805c52a46dd6b3ef8f83f68d27277660945"
POLICIES = ("on", "off")
SCORERS = ("own", "relevance")
HIT_STATES = ("both", "onOnly", "offOnly", "neither")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify_inputs():
    original = (ROOT / "receipt.json").read_bytes()
    assert sha(original) == ORIGINAL_RECEIPT_SHA, "Original policy receipt differs"
    receipt = json.loads(original)
    assert receipt["primaryExternalAttempt"] == "attempt-03"
    assert receipt["questionsPerConfiguration"] == 1986
    assert receipt["status"] == "ALL_CONFIGURED_CELLS_CAPTURED_AND_VALIDATED"
    hashes = {"receipt.json": ORIGINAL_RECEIPT_SHA}
    for path in (JOURNAL, CAPTURES, CAPTURE_RECEIPT, CORPUS, SUMMARY, Path("analyze.py")):
        source_hashes = receipt["analysisSourceSha256"] if path.suffix == ".py" else receipt["artifactSha256"]
        hashes[path.as_posix()] = sha((ROOT / path).read_bytes())
        assert hashes[path.as_posix()] == source_hashes[path.as_posix()], f"Archive hash differs for {path}"
    native = json.loads((ROOT / NATIVE_RECEIPT).read_bytes())
    capture = json.loads((ROOT / CAPTURE_RECEIPT).read_bytes())
    assert native["status"] == "ALL_CONFIGURED_CELLS_COMPLETE" and native["system"] == "langchain"
    assert native["journalSha256"] == capture["inputSha256"] == hashes[JOURNAL.as_posix()]
    assert native["codeCommit"] == capture["codeCommit"] == receipt["executionCodeCommits"]["external"]
    assert native["planCommit"] == capture["planCommit"] == receipt["planCommit"]
    assert native["rows"] == capture["rows"] == 7944
    assert capture["unknown"] == capture["truncated"] == 0
    assert capture["newModelCalls"] == 0
    hashes[NATIVE_RECEIPT.as_posix()] = sha((ROOT / NATIVE_RECEIPT).read_bytes())
    corpus_bytes = gzip.decompress((ROOT / CORPUS).read_bytes())
    assert sha(corpus_bytes) == receipt["corpusExportUncompressedSha256"]
    return receipt, capture, hashes, json.loads(corpus_bytes)


def read_rows(path):
    with gzip.open(ROOT / path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def key(row):
    assert row["system"] == "langchain"
    return row["c"], row["q"], row["policy"], row["scorer"]


def validate_pairs(questions, contents):
    expected = {(c, q, p, s) for c, q in questions for p in POLICIES for s in SCORERS}
    rankings, pools = {}, {}
    for row in read_rows(JOURNAL):
        record = key(row)
        assert record in expected and record not in rankings, "Missing or duplicated journal key"
        c, q, _, _ = record
        question = questions[c, q]
        assert row["category"] == question["category"] and row["question"] == question["question"]
        assert row["answerable"] == (question["category"] != 5)
        assert set(row["gold"]) == set(question["evidence"])
        ranking = tuple(item["source"] for item in row["delivered"])
        above, pool = frozenset(row["aboveIds"]), frozenset(row["poolIds"])
        assert len(ranking) == len(set(ranking)) <= 8
        assert set(ranking) <= above <= pool <= contents[c].keys()
        assert pools.setdefault((c, q), (above, pool)) == (above, pool), "Candidate mask changed across cells"
        rankings[record] = ranking
    assert rankings.keys() == expected, "Incomplete ranked archive"

    delivered = {}
    for row in read_rows(CAPTURES):
        record = key(row)
        assert record in expected and record not in delivered, "Missing or duplicated prompt key"
        c, q, _, _ = record
        assert row["completed"] is True and row["identifiable"] is True and row["truncated"] is False
        assert sha(row["rawSystem"].encode("utf-8")) == row["systemSha256"]
        planned = list(rankings[record][:5])
        state, actual = observed(row["rawSystem"], planned, contents[c])
        assert row["state"] == state and state in {"complete", "absent"}
        assert row["plannedIds"] == row["observedIds"] == actual == planned
        assert row["promptGold"] == len(set(actual) & set(questions[c, q]["evidence"]))
        delivered[record] = tuple(actual)
    assert delivered.keys() == expected, "Incomplete prompt archive"
    return rankings, delivered


def hit_state(on, off):
    if on:
        return "both" if off else "onOnly"
    return "offOnly" if off else "neither"


def summarize(frame, rankings, delivered):
    stages = {"top8": rankings, "actualPrompt": delivered}
    joint = {state: dict.fromkeys(HIT_STATES, 0) for state in HIT_STATES}
    changes = {stage: Counter() for stage in stages}
    by_dialogue = {stage: defaultdict(list) for stage in stages}
    for (c, q), question in frame.items():
        gold = set(question["evidence"])
        states = {}
        for stage, cells in stages.items():
            on, off = (cells[c, q, policy, "own"] for policy in POLICIES)
            gold_on, gold_off = gold.intersection(on), gold.intersection(off)
            state = states[stage] = hit_state(gold_on, gold_off)
            counts = changes[stage]
            counts["orderedSourceChange"] += on != off
            counts["sourceSetChange"] += set(on) != set(off)
            counts["goldSourceSetChange"] += gold_on != gold_off
            counts["goldCountIncrease"] += len(gold_on) > len(gold_off)
            counts["goldCountDecrease"] += len(gold_on) < len(gold_off)
            counts["differentGoldSameCount"] += gold_on != gold_off and len(gold_on) == len(gold_off)
            if gold:
                by_dialogue[stage][c].append((
                    int(bool(gold_on)), int(bool(gold_off)), len(gold_on) / len(gold), len(gold_off) / len(gold),
                ))
        joint[states["top8"]][states["actualPrompt"]] += 1

    results = {}
    for stage, counts in changes.items():
        hit_totals = (
            {state: sum(joint[state].values()) for state in HIT_STATES}
            if stage == "top8"
            else {state: sum(row[state] for row in joint.values()) for state in HIT_STATES}
        )
        dialogues = by_dialogue[stage]
        assert len(dialogues) == 10 and sum(hit_totals.values()) == len(frame)
        macro = {}
        for metric, on_index, off_index in (("hitAny", 0, 1), ("annotatedSourceFraction", 2, 3)):
            on_means = [fmean(row[on_index] for row in rows) for rows in dialogues.values()]
            off_means = [fmean(row[off_index] for row in rows) for rows in dialogues.values()]
            differences = [on - off for on, off in zip(on_means, off_means)]
            macro[metric] = {
                "on": round(fmean(on_means), 9),
                "off": round(fmean(off_means), 9),
                "onMinusOff": round(fmean(differences), 9),
                "dialoguesWithLargerOn": sum(value > 0 for value in differences),
                "dialoguesWithEqual": sum(value == 0 for value in differences),
                "dialoguesWithLargerOff": sum(value < 0 for value in differences),
            }
        results[stage] = {"hitStates": hit_totals, "changes": dict(counts), "dialogueMacro": macro}
    return {
        "questionCount": len(frame),
        "withAnnotatedEvidence": sum(bool(question["evidence"]) for question in frame.values()),
        "dialogueCount": 10,
        "stages": results,
        "pairedTop8StateToPromptState": joint,
    }


def check_against_original(full, primary):
    archived = json.loads((ROOT / SUMMARY).read_bytes())["external"]["langchain"]
    old_switch = archived["validation"]["switchDiagnostics"]["policyUnderOwn"]
    top8 = full["stages"]["top8"]["changes"]
    assert full["questionCount"] == old_switch["questions"]
    assert top8["orderedSourceChange"] == old_switch["differentOrderedTop8"]
    assert top8["goldCountIncrease"] + top8["goldCountDecrease"] == old_switch["differentGoldCountsAt8"]
    assert old_switch["differentThresholdMasks"] == 0
    for population_name, population in (("all", full), ("answerable", primary)):
        previous = archived["populations"][population_name]
        assert population["withAnnotatedEvidence"] == previous["population"]["eligibleQuestions"]
        for stage, metric, archived_metric in (
            ("top8", "hitAny", "hit8"),
            ("top8", "annotatedSourceFraction", "delivered8"),
            ("actualPrompt", "annotatedSourceFraction", "prompt"),
        ):
            macro = population["stages"][stage]["dialogueMacro"][metric]
            for policy in POLICIES:
                expected = previous["policies"][policy + "-own"]["recall"][archived_metric]["mean"]
                assert abs(macro[policy] - expected) <= 0.000000501
        contrast = population["stages"]["top8"]["dialogueMacro"]["hitAny"]["onMinusOff"]
        assert abs(contrast - previous["effects"]["policyOnMinusOffOwnScorer"]["mean"]) <= 0.000000501


def main():
    if not __debug__:
        raise RuntimeError("Archive verification requires Python assertions")
    receipt, capture, hashes, corpus = verify_inputs()
    contents = [{turn["id"]: turn["content"] for turn in dialogue["turns"]} for dialogue in corpus]
    questions = {(c, q): question for c, dialogue in enumerate(corpus) for q, question in enumerate(dialogue["questions"])}
    assert len(corpus) == 10 and len(questions) == 1986
    rankings, delivered = validate_pairs(questions, contents)
    eligible = {key: question for key, question in questions.items() if question["category"] != 5 and question["evidence"]}
    full, primary = (summarize(frame, rankings, delivered) for frame in (questions, eligible))
    check_against_original(full, primary)
    result = {
        "schema": "aijade.p3.langchain-access-refresh-transitions.v1",
        "status": "POST_HOC_DESCRIPTIVE_ARCHIVE_RECOMPUTATION",
        "scope": "Attempt 03, LangChain named access-refresh configuration, native own scorer held fixed. No new run or wider policy inference.",
        "executionCommit": receipt["executionCodeCommits"]["external"],
        "originalPlanCommit": receipt["planCommit"],
        "analysisSourceSha256": sha(Path(__file__).read_bytes()),
        "inputSha256": hashes,
        "archiveChecks": {
            "validatedRankedRows": len(rankings),
            "validatedCompletionCaptures": len(delivered),
            "candidateMasksMatchedAcrossAllCells": True,
            "actualPromptMatchedPlannedFirstFiveAcrossAllCells": True,
            "archivedPromptBudget": capture["budget"],
            "truncatedOrUnknownCaptures": 0,
            "originalStageMeansAndTop8SwitchCountsMatched": True,
            "newModelCalls": 0,
        },
        "metrics": {
            "hitStates": "Any annotated source present in both, ON only, OFF only, or neither cell",
            "dialogueMacro": "Mean within each of ten conversations, then equally across conversations. Questions without any evidence annotation are omitted from these means, and unlocated annotated sources remain in the denominator.",
            "promptBoundary": "Ordered first five native results, verified in captured memory blocks. There was no extra recorded budget truncation. This does not measure generated-answer quality.",
        },
        "allArchivedQuestions": full,
        "answerableWithAnnotatedEvidence": primary,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
