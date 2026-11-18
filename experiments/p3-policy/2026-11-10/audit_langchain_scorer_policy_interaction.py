#!/usr/bin/env python3
"""Recompute archived LangChain scorer × refresh contrasts without inference."""

import json
from collections import Counter, defaultdict
from fractions import Fraction
from statistics import fmean

from analyze import contrast, holm
from audit_langchain_access_refresh import (
    HIT_STATES, POLICIES, ROOT, SCORERS, SUMMARY, check_against_original,
    hit_state, sha, summarize, validate_pairs, verify_inputs,
)

METRICS = ("hitAny", "annotatedSourceFraction")
CELL_PAIRS = tuple((policy, scorer) for scorer in SCORERS for policy in POLICIES)
PREVIOUS = ROOT / "langchain-access-refresh-transitions.json"


def assess_stage(outputs, primary, questions):
    """Form measurement-unit vectors from complete paired source selections."""
    dialogue_order = sorted({c for c, _ in primary})
    hit_states = {scorer: Counter(dict.fromkeys(HIT_STATES, 0)) for scorer in SCORERS}
    turns = {cell: defaultdict(list) for cell in CELL_PAIRS}
    for (c, q), question in primary.items():
        gold = frozenset(question["evidence"])
        for scorer in SCORERS:
            on, off = (len(gold.intersection(outputs[c, q, policy, scorer])) for policy in POLICIES)
            hit_states[scorer][hit_state(on, off)] += 1
            for policy, hits in zip(POLICIES, (on, off)):
                turns[policy, scorer][c].append((int(hits > 0), Fraction(hits, len(gold))))

    changed_order = {}
    for scorer in SCORERS:
        changed_order[scorer] = {
            frame: sum(outputs[c, q, "on", scorer] != outputs[c, q, "off", scorer] for c, q in keys)
            for frame, keys in (("allQuestions", questions), ("primary", primary))
        }

    metrics = {}
    for index, metric in enumerate(METRICS):
        cells = {}
        for cell, dialogues in turns.items():
            # Take exact means before the archived bootstrap consumes the vectors.
            means = []
            for dialogue in dialogue_order:
                rows = dialogues[dialogue]
                means.append(sum(Fraction(row[index]) for row in rows) / len(rows))
            cells[cell] = means

        policy_effects = {
            scorer: [on - off for on, off in zip(cells["on", scorer], cells["off", scorer])]
            for scorer in SCORERS
        }
        own = policy_effects["own"]
        relevance = policy_effects["relevance"]
        interaction = contrast(own, relevance)
        interaction["conversationValues"] = [float(value) for value in interaction["conversationValues"]]
        metrics[metric] = {
            "cellMeans": {f"{policy}-{scorer}": round(fmean(v), 9) for (policy, scorer), v in cells.items()},
            "refreshOnMinusOff": {scorer: round(fmean(values), 9) for scorer, values in policy_effects.items()},
            "interaction": interaction,
        }

    return {
        "hitTransitions": {scorer: dict(states) for scorer, states in hit_states.items()},
        "orderedSourcesChangedByRefresh": changed_order,
        "metrics": metrics,
    }


def verify_prior_results(questions, primary, rankings, delivered, stages):
    """Reconcile the new outputs against both archived independent summaries."""
    raw = PREVIOUS.read_bytes()
    previous = json.loads(raw)
    full = summarize(questions, rankings, delivered)
    native = summarize(primary, rankings, delivered)
    assert previous["answerableWithAnnotatedEvidence"] == native
    assert previous["allArchivedQuestions"] == full
    check_against_original(full, native)
    for stage, result in stages.items():
        native_stage = native["stages"][stage]
        assert result["hitTransitions"]["own"] == native_stage["hitStates"]
        assert result["orderedSourcesChangedByRefresh"]["own"]["primary"] == native_stage["changes"]["orderedSourceChange"]
        for metric, old in native_stage["dialogueMacro"].items():
            assert result["metrics"][metric]["refreshOnMinusOff"]["own"] == old["onMinusOff"]

    original = json.loads((ROOT / SUMMARY).read_bytes())["external"]["langchain"]["populations"]["answerable"]
    for stage, metric, baseline_metric in (
        ("top8", "hitAny", "hit8"),
        ("top8", "annotatedSourceFraction", "delivered8"),
        ("actualPrompt", "annotatedSourceFraction", "prompt"),
    ):
        means = stages[stage]["metrics"][metric]["cellMeans"]
        assert set(means) == set(original["policies"])
        assert all(
            abs(mean - original["policies"][cell]["recall"][baseline_metric]["mean"]) <= 0.000000501
            for cell, mean in means.items()
        )
    return sha(raw)


def main():
    if not __debug__:
        raise RuntimeError("Archive verification requires Python assertions")
    receipt, _, hashes, corpus = verify_inputs()
    contents = [{turn["id"]: turn["content"] for turn in dialogue["turns"]} for dialogue in corpus]
    questions = {(c, q): question for c, dialogue in enumerate(corpus) for q, question in enumerate(dialogue["questions"])}
    primary = {
        key: question for key, question in questions.items() if question["category"] != 5 and question["evidence"]
    }
    assert len(corpus) == 10 and len(questions) == 1986 and len(primary) == 1536
    rankings, delivered = validate_pairs(questions, contents)
    stages = {
        stage: assess_stage(outputs, primary, questions)
        for stage, outputs in (("top8", rankings), ("actualPrompt", delivered))
    }
    hashes[PREVIOUS.name] = verify_prior_results(questions, primary, rankings, delivered, stages)
    family = [result["interaction"] for stage in stages.values() for result in stage["metrics"].values()]
    holm(family)
    result = {
        "schema": "aijade.p3.langchain-scorer-policy-interaction.v1",
        "status": "POST_HOC_ARCHIVE_RECOMPUTATION",
        "scope": "Frozen attempt 03 LangChain time-weighted retriever, recorded relevance-only scorer and access-refresh switch.",
        "contrast": "(refresh on minus off under native scoring) minus (refresh on minus off under relevance-only scoring)",
        "metrics": {
            "hitAny": "binary hit on at least one annotated evidence source",
            "annotatedSourceFraction": "distinct annotated evidence sources present divided by all annotated sources",
        },
        "inference": {
            "unit": "ten dialogues, equally weighted after dialogue-specific question means",
            "interval": "descriptive 95% percentile interval from 10,000 paired dialogue resamples, seed 20261110",
            "signFlip": "exploratory two-sided exact test across 1,024 sign patterns, assuming independent dialogues and null sign symmetry",
            "holmFamily": "four exploratory interactions: two stages crossed with two metrics",
            "limits": "same archived corpus and switch; no preregistered test, independent corpus, other maintenance policy or generated-answer result",
        },
        "provenance": {
            "executionCommit": receipt["executionCodeCommits"]["external"],
            "originalPlanCommit": receipt["planCommit"],
            "analysisSourcesSha256": {
                "audit_langchain_scorer_policy_interaction.py": sha((ROOT / "audit_langchain_scorer_policy_interaction.py").read_bytes()),
                "audit_langchain_access_refresh.py": sha((ROOT / "audit_langchain_access_refresh.py").read_bytes()),
            },
            "inputSha256": hashes,
        },
        "archiveChecks": {
            "rankingRowsValidated": len(rankings),
            "actualPromptRowsValidated": len(delivered),
            "candidateMasksMatchedAcrossAllCells": True,
            "actualPromptMatchedPlannedFirstFiveAcrossAllCells": True,
            "priorNativeTransitionAndOriginalCellMeansMatched": True,
            "newModelCalls": 0,
        },
        "population": {
            "allQuestions": len(questions),
            "primaryEvidenceBearingAnswerable": len(primary),
            "questionsPerDialogue": [sum(key[0] == c for key in primary) for c in range(len(corpus))],
        },
        "stages": stages,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
