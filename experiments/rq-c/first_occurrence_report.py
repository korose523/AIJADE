#!/usr/bin/env python3
"""First and later occurrences of identical requests in retained RQ-C run records.

A run sends many of its requests more than once: the same task prompt in several trials and cells, and the same
program to the verifier each time it is generated again. The runs this tool was written for send every request with
temperature 0 and one fixed seed. The tool counts, run by run, how often the reply to the first occurrence of a
request differs from the replies to its later occurrences, for the verifier and for the generator, and what the
difference does to the skill-level error rates. It reads only trials.jsonl, candidates.jsonl and summary.json of each
run directory.

Definitions (the same texts are written to the report under "definitions").

Scope
  readOnly: candidateProgramsExecuted and modelRequests are always 0. The tool starts no model, uses no network and
    executes no recorded program. Programs and replies are hashed and compared as text.
  scope: Every count belongs to one run or to one pair of runs. Counts of different runs are never added.

Records
  step: One line of trials.jsonl together with the line of candidates.jsonl at the same index. The two files must
    agree on the step number, the skill, the reuse flag and the execution outcome; otherwise the run is refused.
  program: A task together with the SHA-256 of the UTF-8 bytes of the recorded code.
  usable: For a program: true when every recorded execution of it in the run succeeded, false when every one failed,
    null when both occur. Executions are read from the records.
  skill: All steps with one skill identifier: the step that created the skill and the steps that reused it. A reused
    skill keeps the verdict it received when it was created.
  verdict: The verdict recorded for a step (pass or fail). The tool does not read verdicts from reply texts.

Requests
  verifierCall: A step that is not a reuse, in a self-verification cell (sv1-ef0 or sv1-ef1), with a recorded verdict.
    The runner calls the verifier once, when a skill is created.
  verifierRequest: The program of a verifier call. Under the template, model and options of one run the verifier
    prompt is built from the task and the code alone. The request text itself is not stored.
  reply: The stored verifier reply: selfReply when present, otherwise selfRationale, which holds the first 280 UTF-16
    units of the reply. A run that stores no selfReply and has replies of exactly 280 units may have cut them; text
    differences in such a run are a lower bound (storedReplies.textDifferencesAreALowerBound).
  generationCall: A step that is not a reuse. Its output is the recorded generation text.
  generationRequest: A task prompt (kind "plain") is identified by the task. An informed retry (kind "informed": an
    attempt after the first that carries environment feedback or a critique) is identified by the task, by whether
    environment feedback was given, by the critique (the rationale of the previous verifier call for the task in the
    same cell and trial) and by the previous code of the task in the same cell and trial. The environment-feedback
    text is not stored; it is taken to follow from the task and the previous code. The recorded attempt number and
    feedback flags must follow from the earlier steps; otherwise the run is refused. The generation counts are given
    for all requests and, under taskPrompts and informedRetries, for each kind.
  sentAtLeastTwice: The requests with two or more calls in the run. All first-and-later counts are taken over these
    requests.

Counts
  usualLaterText: For a request sent at least twice: the most frequent text among its calls from the second on. Of
    several equally frequent texts the one that occurs first.
  firstDiffers: The text of the first call of a request sent at least twice is not its usual later text
    (firstReplyDiffers for the verifier, firstOutputDiffers for the generator).
  firstReplyDiffersAndVerdictDiffers: Among the requests counted under firstReplyDiffers: the verdict of the first
    call is not the verdict of the usual later reply.
  laterCallsThatDiffer: Calls from the second on, out of laterCalls, whose text is not the usual later text.
  variedRequests: The requests sent at least twice that received more than one text. Their number is
    withMoreThanOneReply for the verifier and withMoreThanOneOutput for the generator. In the pattern each distinct
    text has a letter in order of first appearance (a to z, then ?).
  verdictChanges: The verifier requests sent at least twice that received more than one verdict. Their number is
    withMoreThanOneVerdict. Each is listed with its task, the first eight hexadecimal digits of the code SHA-256,
    whether the program is usable, the steps of its calls and the verdicts in call order (P pass, F fail).
  consecutiveOccurrences: The stability rule. Each occurrence of a request after its first forms a pair with the
    occurrence before it. firstToSecond holds the pairs of the first and second occurrence, fromSecondOn the pairs of
    later occurrences. A pair has an intervening request when, between its two occurrences, the same layer sent a
    different request for the same task (for the verifier: the same task with different code). changes counts the
    pairs whose two texts differ, and changesFromSecondOn lists those of fromSecondOn.
  staticRelabelling: The skill-level confusion matrix of the self-verification cells. Truth is the last recorded
    execution of the skill, as in summarize_department_regeneration.py: in this item a skill is usable when that
    execution succeeded. tp: passed and usable; fp: passed and not usable; fn: rejected and usable; tn: rejected and
    not usable. observed uses the recorded verdict of each skill. allFirstCall gives every skill the verdict of the
    first verifier call on its program in the run. allLaterCall gives every skill the most frequent verdict among the
    later calls on its program (of two equally frequent verdicts the one that occurs first), or the only verdict when
    the program was verified once. The skills themselves stay as recorded: the regenerations that another verdict
    would have caused are not modelled. falsePassRate is fp / (fp + tn) and falseRejectRate is fn / (fn + tp).
  pairs: For two runs with the same recorded request settings (model and its digest, verifier template, temperature,
    sampling seed, context size, reply limit, verdict fallback, request policy and public task bank): the steps at
    which both runs called the verifier. sameTaskAndCode counts the pairs with the same task and the same code at
    that step, how many of them differ in verdict and in reply text, and the programs whose verdict differs, with
    the verdicts of all calls on the program in each run. When either run may have cut its replies
    (storedReplies.textDifferencesAreALowerBound), the reply texts of a pair are compared over their first 280
    UTF-16 units, which both runs store, and the count is a lower bound (textDifferencesAreALowerBound). Pairs with
    different code at the same step are counted apart. verifierCallInOneRunOnly counts the steps at which only one of
    the two runs called the verifier. Runs with different request settings are not paired.

Special runs
  resumedRun: A resumed run replayed the first generations and verifier replies from the record of the interrupted
    run instead of requesting them (summary.json, resumed.replayedGenerations and resumed.replayedVerifications; they
    lie in the steps before resumed.replayedSteps). Replayed calls are left out of every item. staticRelabelling is
    null when verifier replies were replayed.
  inertRun: The inert control sends one task prompt per task and returns that text for every later attempt. Only
    the first generation call of each task is a request; the verifier is called as in every other run.
  exploratory: true for a run named with --exploratory. The flag changes no count.

Usage: first_occurrence_report.py --run LABEL=DIR [--run LABEL=DIR ...] [--reference LABEL=DIR ...]
           [--pair FIRST:SECOND ...] [--exploratory LABEL ...] [--note TEXT ...] [--out FILE]
  --run          a run directory to analyse
  --reference    a run directory read only as the other side of a pair
  --pair         compare the verifier calls of two labelled runs step by step
  --exploratory  mark a run as exploratory in the report
  --note         a statement copied into the report
  --out          write the report to a new file; an existing file is never overwritten
An input directory inside this repository is recorded by its path. Any other input is recorded by the name of its
directory only and marked private. Every input file is recorded with its SHA-256, and the report carries the SHA-256
of this file.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SCHEMA = "aijade.p2-r.first-occurrence.v1"
RECORD_FILES = ("trials.jsonl", "candidates.jsonl", "summary.json")
CONDITIONS = ("sv0-ef0", "sv0-ef1", "sv1-ef0", "sv1-ef1")
RATIONALE_UNITS = 280

DEFINITIONS = {
    "readOnly":
        "candidateProgramsExecuted and modelRequests are always 0. The tool starts no model, uses no network and "
        "executes no recorded program. Programs and replies are hashed and compared as text.",
    "scope":
        "Every count belongs to one run or to one pair of runs. Counts of different runs are never added.",
    "step":
        "One line of trials.jsonl together with the line of candidates.jsonl at the same index. The two files must "
        "agree on the step number, the skill, the reuse flag and the execution outcome; otherwise the run is refused.",
    "program":
        "A task together with the SHA-256 of the UTF-8 bytes of the recorded code.",
    "usable":
        "For a program: true when every recorded execution of it in the run succeeded, false when every one failed, "
        "null when both occur. Executions are read from the records.",
    "skill":
        "All steps with one skill identifier: the step that created the skill and the steps that reused it. A reused "
        "skill keeps the verdict it received when it was created.",
    "verdict":
        "The verdict recorded for a step (pass or fail). The tool does not read verdicts from reply texts.",
    "verifierCall":
        "A step that is not a reuse, in a self-verification cell (sv1-ef0 or sv1-ef1), with a recorded verdict. "
        "The runner calls the verifier once, when a skill is created.",
    "verifierRequest":
        "The program of a verifier call. Under the template, model and options of one run the verifier "
        "prompt is built from the task and the code alone. The request text itself is not stored.",
    "reply":
        "The stored verifier reply: selfReply when present, otherwise selfRationale, which holds the first 280 "
        "UTF-16 units of the reply. A run that stores no selfReply and has replies of exactly 280 units may have cut "
        "them; text differences in such a run are a lower bound (storedReplies.textDifferencesAreALowerBound).",
    "generationCall":
        "A step that is not a reuse. Its output is the recorded generation text.",
    "generationRequest":
        "A task prompt (kind \"plain\") is identified by the task. An informed retry (kind \"informed\": an "
        "attempt after the first that carries environment feedback or a critique) is identified by the task, by "
        "whether environment feedback was given, by the critique (the rationale of the previous verifier call for "
        "the task in the same cell and trial) and by the previous code of the task in the same cell and trial. The "
        "environment-feedback text is not stored; it is taken to follow from the task and the previous code. The "
        "recorded attempt number and feedback flags must follow from the earlier steps; otherwise the run is "
        "refused. The generation counts are given for all requests and, under taskPrompts and informedRetries, for "
        "each kind.",
    "sentAtLeastTwice":
        "The requests with two or more calls in the run. All first-and-later counts are taken over these requests.",
    "usualLaterText":
        "For a request sent at least twice: the most frequent text among its calls from the second on. Of "
        "several equally frequent texts the one that occurs first.",
    "firstDiffers":
        "The text of the first call of a request sent at least twice is not its usual later text "
        "(firstReplyDiffers for the verifier, firstOutputDiffers for the generator).",
    "firstReplyDiffersAndVerdictDiffers":
        "Among the requests counted under firstReplyDiffers: the verdict of the first "
        "call is not the verdict of the usual later reply.",
    "laterCallsThatDiffer":
        "Calls from the second on, out of laterCalls, whose text is not the usual later text.",
    "variedRequests":
        "The requests sent at least twice that received more than one text. Their number is "
        "withMoreThanOneReply for the verifier and withMoreThanOneOutput for the generator. In the pattern each "
        "distinct text has a letter in order of first appearance (a to z, then ?).",
    "verdictChanges":
        "The verifier requests sent at least twice that received more than one verdict. Their number is "
        "withMoreThanOneVerdict. Each is listed with its task, the first eight hexadecimal digits of the code "
        "SHA-256, whether the program is usable, the steps of its calls and the verdicts in call order "
        "(P pass, F fail).",
    "consecutiveOccurrences":
        "The stability rule. Each occurrence of a request after its first forms a pair with the "
        "occurrence before it. firstToSecond holds the pairs of the first and second occurrence, fromSecondOn the "
        "pairs of later occurrences. A pair has an intervening request when, between its two occurrences, the same "
        "layer sent a different request for the same task (for the verifier: the same task with different code). "
        "changes counts the pairs whose two texts differ, and changesFromSecondOn lists those of fromSecondOn.",
    "staticRelabelling":
        "The skill-level confusion matrix of the self-verification cells. Truth is the last recorded "
        "execution of the skill, as in summarize_department_regeneration.py: in this item a skill is usable when "
        "that execution succeeded. tp: passed and usable; fp: passed and not usable; fn: rejected and usable; tn: "
        "rejected and not usable. observed uses the recorded verdict of each skill. allFirstCall gives every skill "
        "the verdict of the first verifier call on its program in the run. allLaterCall gives every skill the most "
        "frequent verdict among the later calls on its program (of two equally frequent verdicts the one that "
        "occurs first), or the only verdict when the program was verified once. The skills themselves stay as "
        "recorded: the regenerations that another verdict would have caused are not modelled. falsePassRate is "
        "fp / (fp + tn) and falseRejectRate is fn / (fn + tp).",
    "pairs":
        "For two runs with the same recorded request settings (model and its digest, verifier template, "
        "temperature, sampling seed, context size, reply limit, verdict fallback, request policy and public task "
        "bank): the steps at which both runs called the verifier. sameTaskAndCode counts the pairs with the same "
        "task and the same code at that step, how many of them differ in verdict and in reply text, and the "
        "programs whose verdict differs, with the verdicts of all calls on the program in each run. When either run "
        "may have cut its replies (storedReplies.textDifferencesAreALowerBound), the reply texts of a pair are "
        "compared over their first 280 UTF-16 units, which both runs store, and the count is a lower bound "
        "(textDifferencesAreALowerBound). Pairs with different code at the same step are counted apart. "
        "verifierCallInOneRunOnly counts the steps at which only one of the two runs called the verifier. Runs with "
        "different request settings are not paired.",
    "resumedRun":
        "A resumed run replayed the first generations and verifier replies from the record of the interrupted "
        "run instead of requesting them (summary.json, resumed.replayedGenerations and "
        "resumed.replayedVerifications; they lie in the steps before resumed.replayedSteps). Replayed calls are left "
        "out of every item. staticRelabelling is null when verifier replies were replayed.",
    "inertRun":
        "The inert control sends one task prompt per task and returns that text for every later attempt. Only "
        "the first generation call of each task is a request; the verifier is called as in every other run.",
    "exploratory":
        "true for a run named with --exploratory. The flag changes no count.",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_text(text):
    return sha256_bytes(text.encode("utf-8", "surrogatepass"))


def utf16_units(text):
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def decode_lines(data, name):
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    rows = []
    for number, line in enumerate(data.split(b"\n"), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line.decode("utf-8"))
        except ValueError as exc:
            raise ValueError(f"{name}, line {number}: {exc}") from None
        require(isinstance(row, dict), f"{name}, line {number}: expected an object")
        rows.append(row)
    return rows


def parse_steps(trials, candidates):
    """Merge the two record files step by step and check every field the analysis reads."""
    require(len(trials) == len(candidates), f"{len(trials)} trial records but {len(candidates)} candidate records")
    steps, skills = [], {}
    for index, (t, c) in enumerate(zip(trials, candidates)):
        condition, reused, ok = t.get("condition"), t.get("reused"), t.get("execOk")
        require(condition in CONDITIONS, f"step {index}: unexpected condition")
        require(type(reused) is bool and type(ok) is bool, f"step {index}: missing reuse flag or execution outcome")
        require(type(c.get("step")) is int and c["step"] == index and c.get("skillId") == t.get("skillId")
                and c.get("reused") is reused and c.get("execOk") is ok,
                f"step {index}: trial and candidate records disagree")
        require(all(isinstance(t.get(key), str) and t[key] for key in ("taskId", "skillId")),
                f"step {index}: missing task or skill identifier")
        require(all(type(t.get(key)) is int for key in ("trial", "round", "attempt"))
                and all(type(t.get(key)) is bool for key in ("hadEnvFeedback", "hadSelfCritique")),
                f"step {index}: missing position, attempt or feedback flags")
        verifies = condition.startswith("sv1-")
        verdict = t.get("selfVerdict")
        require(verdict in (("pass", "fail") if verifies else (None,)), f"step {index}: missing or unexpected verdict")
        code, generation, rationale = c.get("code"), c.get("generation"), c.get("selfRationale")
        require(isinstance(code, str), f"step {index}: missing code")
        require(generation is None if reused else isinstance(generation, str),
                f"step {index}: a generation text belongs to every new skill and to no reuse")
        called = verifies and not reused
        require(isinstance(rationale, str) if called else rationale is None,
                f"step {index}: a verifier reply belongs to every new skill of a self-verification cell only")
        require("selfReply" not in c or (called and isinstance(c["selfReply"], str)),
                f"step {index}: unexpected full verifier reply")
        step = {
            "step": index, "condition": condition, "selfVerification": verifies,
            "envFeedback": condition.endswith("-ef1"), "trial": t["trial"], "round": t["round"], "task": t["taskId"],
            "skill": t["skillId"], "reused": reused, "attempt": t["attempt"], "hadEnvFeedback": t["hadEnvFeedback"],
            "hadSelfCritique": t["hadSelfCritique"], "verdict": verdict, "execOk": ok, "code": code,
            "codeSha": sha256_text(code), "generation": generation, "rationale": rationale,
            "reply": c.get("selfReply", rationale), "fullReplyStored": "selfReply" in c,
        }
        identity = (condition, step["trial"], step["task"], verdict, step["codeSha"])
        known = skills.get(step["skill"])
        require(reused is (known is not None), f"step {index}: skill reuse does not match the order of generation")
        require(known is None or known == identity, f"step {index}: identity, verdict or code changed within a skill")
        skills[step["skill"]] = identity
        steps.append(step)
    return steps


def replayed_counts(summary):
    resumed = summary.get("resumed")
    if resumed is None:
        return None
    keys = ("replayedSteps", "replayedGenerations", "replayedVerifications")
    require(isinstance(resumed, dict) and all(type(resumed.get(key)) is int and resumed[key] >= 0 for key in keys),
            "summary.json: a resumed run must count its replayed steps, generations and verifications")
    return {key: resumed[key] for key in keys}


def request_settings(summary):
    """The recorded settings that, with the task and the code, fix a verifier request and the reading of its reply."""
    config, sampling = summary["config"], summary["sampling"]
    return {
        "model": config.get("model"),
        "modelDigest": sampling.get("modelDigest"),
        "verifyTemplate": config.get("verifyTemplate", "A"),
        "temperature": sampling.get("temperature"),
        "samplingSeed": sampling.get("seed"),
        "numCtx": config.get("numCtx"),
        "maxReplyTokens": config.get("maxReplyTokens"),
        "verdictFallback": config.get("verdictFallback", False),
        "requestPolicySha256": config.get("requestPolicySha256"),
        "publicBankManifestSha256": config.get("publicBankManifestSha256"),
    }


def live_calls(calls, replayed, key):
    """Drop the calls that a resumed run answered from the record of the interrupted run."""
    if replayed is None:
        return calls
    count, boundary = replayed[key], replayed["replayedSteps"]
    require(count <= len(calls) and all(call["step"] < boundary for call in calls[:count])
            and all(call["step"] >= boundary for call in calls[count:]),
            "the replayed calls of the resumed run do not end where its replayed steps end")
    return calls[count:]


def verifier_calls(steps, replayed=None):
    calls = [{"step": s["step"], "task": s["task"], "codeSha": s["codeSha"], "request": (s["task"], s["codeSha"]),
              "text": s["reply"], "verdict": s["verdict"], "rationale": s["rationale"],
              "fullReplyStored": s["fullReplyStored"]}
             for s in steps if s["selfVerification"] and not s["reused"]]
    return live_calls(calls, replayed, "replayedVerifications")


def generation_calls(steps, inert=False, replayed=None):
    """The generation requests of the run in the order sent, each with the key that identifies its prompt."""
    state, calls = {}, []
    for s in steps:
        memory = state.setdefault((s["condition"], s["trial"], s["task"]),
                                  {"attempts": 0, "code": None, "critique": None, "executed": False})
        if not s["reused"]:
            feedback = s["envFeedback"] and memory["executed"]
            critique = memory["critique"] if s["selfVerification"] else None
            recorded = (s["attempt"], s["hadEnvFeedback"], s["hadSelfCritique"])
            require(recorded == (memory["attempts"], feedback, critique is not None),
                    f"step {s['step']}: the recorded attempt or feedback flags do not follow from the earlier steps")
            informed = (feedback or critique is not None) and s["attempt"] > 0
            request = ("informed", s["task"], feedback, critique, memory["code"]) if informed else ("plain", s["task"])
            calls.append({"step": s["step"], "task": s["task"], "request": request, "kind": request[0],
                          "text": s["generation"]})
            memory["attempts"] += 1
            memory["code"] = s["code"]
            if s["selfVerification"]:
                memory["critique"] = s["rationale"]
        memory["executed"] = True
    calls = live_calls(calls, replayed, "replayedGenerations")
    if inert:   # the client keeps the first generation of each task; later attempts are not requests
        first = {}
        for call in calls:
            first.setdefault(call["task"], dict(call, request=("plain", call["task"]), kind="plain"))
        calls = list(first.values())
    return calls


def parse_run(files):
    """files: the bytes of trials.jsonl, candidates.jsonl and summary.json. Returns the checked run."""
    summary = json.loads(files["summary.json"].decode("utf-8-sig"))
    require(isinstance(summary, dict) and isinstance(summary.get("config"), dict)
            and isinstance(summary.get("sampling"), dict),
            "summary.json must hold the run configuration and its sampling record")
    inert = summary["config"].get("inert", False)
    require(type(inert) is bool, "summary.json: config.inert must be a boolean")
    steps = parse_steps(decode_lines(files["trials.jsonl"], "trials.jsonl"),
                        decode_lines(files["candidates.jsonl"], "candidates.jsonl"))
    replayed = replayed_counts(summary)
    return {"steps": steps, "summary": summary, "inert": inert, "replayed": replayed,
            "verifierCalls": verifier_calls(steps, replayed),
            "generationCalls": generation_calls(steps, inert, replayed),
            "fileSha256": {name: sha256_bytes(files[name]) for name in RECORD_FILES}}


def load_run(directory):
    directory = Path(directory)
    files = {name: (directory / name).read_bytes() for name in RECORD_FILES}
    try:
        return parse_run(files)
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"{directory.name}: {exc}") from None


def usual(values):
    """The most frequent value; of several equally frequent values the one that occurs first."""
    counts = collections.Counter(values)
    best = max(counts.values())
    return next(value for value in values if counts[value] == best)


def pattern(values):
    letters = {}
    for value in values:
        letters.setdefault(value, chr(ord("a") + len(letters)) if len(letters) < 26 else "?")
    return "".join(letters[value] for value in values)


def by_request(calls):
    groups = {}
    for call in calls:
        groups.setdefault(call["request"], []).append(call)
    return groups


def occurrence_counts(calls):
    """Counts over the requests sent at least twice, and the per-request facts each layer adds its own fields to."""
    groups = by_request(calls)
    repeated = []
    for group in groups.values():
        if len(group) < 2:
            continue
        texts = [call["text"] for call in group]
        common = usual(texts[1:])
        repeated.append({"calls": group, "texts": texts, "usual": common, "firstDiffers": texts[0] != common,
                         "laterThatDiffer": sum(text != common for text in texts[1:]),
                         "varied": len(set(texts)) > 1})
    counts = {
        "calls": len(calls), "requests": len(groups), "sentAtLeastTwice": len(repeated),
        "laterCalls": sum(len(r["texts"]) - 1 for r in repeated),
        "laterCallsThatDiffer": sum(r["laterThatDiffer"] for r in repeated),
    }
    return counts, repeated


def consecutive_occurrences(calls, describe):
    """The stability rule: text changes between consecutive occurrences of one request, with and without an
    intervening request of the same layer for the same task."""
    last, latest = {}, {}   # request -> (position, text, occurrences so far); task -> position of its latest request
    table = collections.Counter()
    changes = []
    for position, call in enumerate(calls):
        request, seen = call["request"], 0
        if request in last:
            before, text, seen = last[request]
            intervening = latest[call["task"]] > before   # a request of the task after that one is a different one
            stage = "firstToSecond" if seen == 1 else "fromSecondOn"
            changed = call["text"] != text
            table[stage, intervening, changed] += 1
            if changed and stage == "fromSecondOn":
                changes.append(dict(describe(call), step=call["step"], interveningRequest=intervening))
        last[request] = (position, call["text"], seen + 1)
        latest[call["task"]] = position
    result = {
        stage: {name: {"pairs": table[stage, flag, True] + table[stage, flag, False],
                       "changes": table[stage, flag, True]}
                for name, flag in (("withoutInterveningRequest", False), ("withInterveningRequest", True))}
        for stage in ("firstToSecond", "fromSecondOn")
    }
    result["changesFromSecondOn"] = changes
    return result


def program_executions(steps):
    """program -> [executions that succeeded, executions that failed], over every step of the run."""
    tally = collections.defaultdict(lambda: [0, 0])
    for s in steps:
        tally[s["task"], s["codeSha"]][0 if s["execOk"] else 1] += 1
    return tally


def usable(tally, program):
    succeeded, failed = tally[program]
    return None if succeeded and failed else bool(succeeded)


def verdict_letters(calls):
    return "".join("P" if call["verdict"] == "pass" else "F" for call in calls)


def describe_program(call):
    return {"task": call["task"], "codeSha256Prefix": call["codeSha"][:8]}


def describe_generation(call):
    return {"task": call["task"], "kind": call["kind"]}


def verification_layer(calls, executions):
    counts, repeated = occurrence_counts(calls)
    verdict_differs, changes, varied = 0, [], []
    for r in repeated:
        group = r["calls"]
        if r["firstDiffers"]:
            later_verdict = next(call["verdict"] for call in group[1:] if call["text"] == r["usual"])
            verdict_differs += group[0]["verdict"] != later_verdict
        if len({call["verdict"] for call in group}) > 1:
            changes.append(dict(describe_program(group[0]), usable=usable(executions, group[0]["request"]),
                                steps=[call["step"] for call in group], verdicts=verdict_letters(group)))
        if r["varied"]:
            varied.append(dict(describe_program(group[0]), calls=len(group), firstStep=group[0]["step"],
                               replies=pattern(r["texts"])))
    counts.update({
        "firstReplyDiffers": sum(r["firstDiffers"] for r in repeated),
        "firstReplyDiffersAndVerdictDiffers": verdict_differs,
        "withMoreThanOneReply": len(varied),
        "withMoreThanOneVerdict": len(changes),
        "verdictChanges": changes,
        "variedRequests": varied,
        "consecutiveOccurrences": consecutive_occurrences(calls, describe_program),
    })
    return counts


def generation_layer(calls):
    counts, repeated = occurrence_counts(calls)
    varied = [dict(describe_generation(r["calls"][0]), calls=len(r["calls"]), firstStep=r["calls"][0]["step"],
                   outputs=pattern(r["texts"]))
              for r in repeated if r["varied"]]
    counts.update({
        "firstOutputDiffers": sum(r["firstDiffers"] for r in repeated),
        "withMoreThanOneOutput": len(varied),
        "variedRequests": varied,
        "consecutiveOccurrences": consecutive_occurrences(calls, describe_generation),
    })
    for name, kind in (("taskPrompts", "plain"), ("informedRetries", "informed")):
        chosen = [r for r in repeated if r["calls"][0]["kind"] == kind]
        counts[name] = {
            "calls": sum(call["kind"] == kind for call in calls),
            "requests": len({call["request"] for call in calls if call["kind"] == kind}),
            "sentAtLeastTwice": len(chosen),
            "firstOutputDiffers": sum(r["firstDiffers"] for r in chosen),
            "withMoreThanOneOutput": sum(r["varied"] for r in chosen),
        }
    return counts


def rate(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "estimate": numerator / denominator if denominator else None}


def confusion(rows):
    """rows: (passed, usable) per skill."""
    cells = collections.Counter(("t" if passed == ok else "f") + ("p" if passed else "n") for passed, ok in rows)
    table = {cell: cells[cell] for cell in ("tp", "fp", "fn", "tn")}
    return {"confusion": table, "falsePassRate": rate(table["fp"], table["fp"] + table["tn"]),
            "falseRejectRate": rate(table["fn"], table["fn"] + table["tp"])}


def static_relabelling(steps, calls):
    """The observed skill-level confusion, and the same skills with the first-call or the later-call verdict of
    their program."""
    skills = {}
    for s in steps:
        if s["selfVerification"]:   # the entry of the skill's last step stays: truth is its last execution
            skills[s["skill"]] = ((s["task"], s["codeSha"]), s["verdict"], s["execOk"])
    first, later = {}, {}
    for program, group in by_request(calls).items():
        verdicts = [call["verdict"] for call in group]
        first[program] = verdicts[0]
        later[program] = usual(verdicts[1:]) if len(verdicts) > 1 else verdicts[0]
    require(len(skills) == len(calls) and all(program in first for program, _, _ in skills.values()),
            "the judged skills do not match the verifier calls")
    return {
        "skills": len(skills),
        "observed": confusion((verdict == "pass", ok) for _, verdict, ok in skills.values()),
        "allFirstCall": confusion((first[program] == "pass", ok) for program, _, ok in skills.values()),
        "allLaterCall": confusion((later[program] == "pass", ok) for program, _, ok in skills.values()),
    }


def stored_replies(calls):
    full = sum(call["fullReplyStored"] for call in calls)
    at_limit = sum(not call["fullReplyStored"] and utf16_units(call["rationale"]) == RATIONALE_UNITS
                   for call in calls)
    result = {"withFullText": full, "atTheLimitWithoutFullText": at_limit,
              "textDifferencesAreALowerBound": full == 0 and at_limit > 0}
    if result["textDifferencesAreALowerBound"]:
        result["statement"] = (
            f"This run stores no full verifier reply, and {at_limit} of its stored replies have exactly "
            f"{RATIONALE_UNITS} UTF-16 units. They may have been cut, so the counts of differing reply texts are a "
            "lower bound.")
    return result


def analyse_run(run):
    steps, replayed, calls = run["steps"], run["replayed"], run["verifierCalls"]
    relabel = not (replayed and replayed["replayedVerifications"])
    return {
        "steps": len(steps),
        "skills": len({s["skill"] for s in steps}),
        "inert": run["inert"],
        "resumed": replayed,
        "storedReplies": stored_replies(calls),
        "verification": verification_layer(calls, program_executions(steps)),
        "generation": generation_layer(run["generationCalls"]),
        "staticRelabelling": static_relabelling(steps, calls) if relabel else None,
    }


def pair_runs(first, second):
    """Verifier calls of two runs at the same step: the same task and code, kept apart from different code."""
    settings = request_settings(first["summary"]), request_settings(second["summary"])
    different = sorted(key for key in settings[0] if settings[0][key] != settings[1][key])
    require(not different, "the two runs did not send their verifier requests under the same recorded settings: "
            + ", ".join(different))
    a = {call["step"]: call for call in first["verifierCalls"]}
    b = {call["step"]: call for call in second["verifierCalls"]}
    both = sorted(set(a) & set(b))
    same = [step for step in both if a[step]["request"] == b[step]["request"]]
    other_code = [step for step in both
                  if a[step]["task"] == b[step]["task"] and a[step]["codeSha"] != b[step]["codeSha"]]
    flipped = [step for step in same if a[step]["verdict"] != b[step]["verdict"]]
    executions = program_executions(first["steps"]), program_executions(second["steps"])
    groups = by_request(first["verifierCalls"]), by_request(second["verifierCalls"])
    programs = []
    for program in dict.fromkeys(a[step]["request"] for step in flipped):
        entry = dict(describe_program(groups[0][program][0]),
                     pairs=sum(a[step]["request"] == program for step in same),
                     verdictDiffers=sum(a[step]["request"] == program for step in flipped))
        for side, index in (("first", 0), ("second", 1)):
            entry[side] = {"calls": len(groups[index][program]), "verdicts": verdict_letters(groups[index][program]),
                           "usable": usable(executions[index], program)}
        programs.append(entry)
    lower_bound = any(stored_replies(run["verifierCalls"])["textDifferencesAreALowerBound"] for run in (first, second))
    text = "rationale" if lower_bound else "text"   # replies that may be cut: compare the part that both runs store
    return {
        "stepsWithAVerifierCallInBothRuns": len(both),
        "verifierCallInOneRunOnly": {"first": len(set(a) - set(b)), "second": len(set(b) - set(a))},
        "sameTaskAndCode": {
            "pairs": len(same),
            "verdictDiffers": len(flipped),
            "replyTextDiffers": sum(a[step][text] != b[step][text] for step in same),
            "programsWithADifferentVerdict": programs,
        },
        "differentCodeAtTheSameStep": {
            "pairs": len(other_code),
            "verdictDiffers": sum(a[step]["verdict"] != b[step]["verdict"] for step in other_code),
        },
        "differentTaskAtTheSameStep": len(both) - len(same) - len(other_code),
        "textDifferencesAreALowerBound": lower_bound,
    }


def input_record(directory, run, role):
    """What the report says about an input: a repository path, or for a private input the directory name only."""
    resolved = Path(directory).resolve()
    private = not resolved.is_relative_to(REPO)
    sampling = run["summary"]["sampling"]
    settings = dict(request_settings(run["summary"]), ollamaVersion=sampling.get("ollamaVersion"),
                    warmUp=sampling.get("warmUp"))
    return {"directory": resolved.name if private else resolved.relative_to(REPO).as_posix(), "private": private,
            "role": role, "sha256": run["fileSha256"], "settings": settings}


def tool_record():
    path = Path(__file__).resolve()
    return {"file": path.relative_to(REPO).as_posix(), "sha256": sha256_bytes(path.read_bytes())}


def labelled(values, option):
    result = {}
    for value in values:
        label, separator, directory = value.partition("=")
        require(separator and label and directory and ":" not in label,
                f"{option} takes LABEL=DIR, and a label holds no colon: {value}")
        require(label not in result, f"{option}: the label {label} is given twice")
        result[label] = Path(directory)
    return result


def build_report(runs, references=None, pairs=(), exploratory=(), notes=()):
    """runs, references: label -> run directory. pairs: (first label, second label). Returns the report."""
    references = dict(references or {})
    directories = {**runs, **references}
    require(runs, "at least one --run is needed")
    require(not set(runs) & set(references), "a label is a run or a reference, not both")
    require(all(label in runs for label in exploratory), "--exploratory names a label that is not a --run")
    for pair in pairs:
        require(len(pair) == 2 and pair[0] != pair[1] and all(label in directories for label in pair),
                f"--pair takes FIRST:SECOND, two different labels of runs or references: {':'.join(pair)}")
    require(len(set(pairs)) == len(pairs), "a pair is given twice")
    loaded = {label: load_run(directory) for label, directory in directories.items()}
    return {
        "schema": SCHEMA,
        "tool": tool_record(),
        "candidateProgramsExecuted": 0,
        "modelRequests": 0,
        "definitions": DEFINITIONS,
        "notes": list(notes),
        "inputs": {label: input_record(directories[label], run, "run" if label in runs else "reference")
                   for label, run in loaded.items()},
        "runs": {label: dict(analyse_run(loaded[label]), exploratory=label in exploratory) for label in runs},
        "pairs": {f"{first} -> {second}": dict(pair_runs(loaded[first], loaded[second]), first=first, second=second)
                  for first, second in pairs},
    }


def encoded(report):
    return json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", action="append", default=[], metavar="LABEL=DIR", help="a run directory to analyse")
    parser.add_argument("--reference", action="append", default=[], metavar="LABEL=DIR",
                        help="a run directory read only as the other side of a pair")
    parser.add_argument("--pair", action="append", default=[], metavar="FIRST:SECOND",
                        help="compare the verifier calls of two labelled runs step by step")
    parser.add_argument("--exploratory", action="append", default=[], metavar="LABEL",
                        help="mark a run as exploratory in the report")
    parser.add_argument("--note", action="append", default=[], metavar="TEXT",
                        help="a statement copied into the report")
    parser.add_argument("--out", type=Path, metavar="FILE",
                        help="new report file; an existing file is never overwritten")
    args = parser.parse_args(argv)
    try:
        require(args.out is None or not args.out.exists(), f"{args.out} exists and is not overwritten")
        pairs = [tuple(value.split(":")) for value in args.pair]
        text = encoded(build_report(labelled(args.run, "--run"), labelled(args.reference, "--reference"), pairs,
                                    args.exploratory, args.note))
        if args.out is None:
            sys.stdout.write(text)
        else:
            with args.out.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
            print(json.dumps({"out": args.out.name, "sha256": sha256_text(text), "runs": len(args.run),
                              "pairs": len(pairs)}))
    except (OSError, ValueError) as exc:
        parser.exit(2, f"{exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
