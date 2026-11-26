"""Offline tests for the first-occurrence report, on synthetic records and on the retained public runs.

No model is called and no recorded program is executed. Temporary files go to a new directory under TMPDIR when that
variable is set, otherwise under the system's temporary directory, and never inside the repository.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import first_occurrence_report as report

HERE = Path(__file__).resolve().parent
GROUPS = ("second-family", "template-a", "template-b")
RUN = "rq-c-s42-ollama-t30-r5"
PUBLIC_RUNS = {
    "main": f"redo/{RUN}",
    "inert": f"redo/{RUN}-INERT",
    "archive/second-family": f"family-gpu/{RUN}",
    "archive/template-a": f"template-gpu/A/{RUN}",
    "archive/template-b": f"template-gpu/B/{RUN}",
    **{f"host2-local/{group}": f"host2-local-20261119/delivered/regeneration/{group}/{RUN}" for group in GROUPS},
}
PUBLIC_PAIRS = [(f"archive/{group}", f"host2-local/{group}") for group in GROUPS]
REPLAYED = ("replayedSteps", "replayedGenerations", "replayedVerifications")


def temporary_directory():
    base = os.environ.get("TMPDIR")
    root = Path(base or tempfile.gettempdir()).resolve()
    if root == report.REPO or report.REPO in root.parents:
        raise RuntimeError("the temporary files of this test must stay outside the repository")
    if base:
        root.mkdir(parents=True, exist_ok=True)   # tempfile would fall back to another directory if it were missing
    return tempfile.TemporaryDirectory(prefix="first-occurrence-", dir=str(root))


def sha8(code):
    return report.sha256_text(code)[:8]


def pick(mapping, *keys):
    return tuple(mapping[key] for key in keys)


class Recorder:
    """Writes run records the way the harness numbers them: within a trial a task keeps its skill until a new one
    is made, and every new skill is one more attempt."""

    def __init__(self, resumed=None, **config):
        self.trials, self.candidates, self.state = [], [], {}
        self.summary = {"config": {"model": "synthetic", "numCtx": 4096, "maxReplyTokens": 4096, **config},
                        "sampling": {"temperature": 0, "seed": 7, "modelDigest": "0" * 64}}
        if resumed is not None:
            self.summary["resumed"] = dict(zip(REPLAYED, resumed))

    def _memory(self, condition, trial, task):
        return self.state.setdefault((condition, trial, task),
                                     {"attempts": 0, "executed": False, "critique": None, "skill": None})

    def new(self, condition, trial, round_, task, code, reply=None, ok=True, generation=None):
        memory = self._memory(condition, trial, task)
        verifies = condition.startswith("sv1-")
        verdict = ("pass" if reply.startswith("PASS") else "fail") if verifies else None
        skill = f"{condition}-t{trial}-r{round_}-{task}"
        self.trials.append({
            "condition": condition, "trial": trial, "round": round_, "taskId": task, "skillId": skill,
            "reused": False, "attempt": memory["attempts"],
            "hadEnvFeedback": condition.endswith("-ef1") and memory["executed"],
            "hadSelfCritique": verifies and memory["critique"] is not None, "selfVerdict": verdict, "execOk": ok})
        candidate = {"step": len(self.candidates), "skillId": skill, "reused": False, "execOk": ok, "code": code,
                     "generation": "```js\n" + code + "\n```" if generation is None else generation,
                     "selfRationale": reply[:280] if verifies else None}
        if verifies and len(reply) > 280:
            candidate["selfReply"] = reply
        self.candidates.append(candidate)
        memory.update(attempts=memory["attempts"] + 1, executed=True, skill=(skill, code, verdict))
        if verifies:
            memory["critique"] = reply[:280]

    def reuse(self, condition, trial, round_, task, ok=True):
        memory = self._memory(condition, trial, task)
        skill, code, verdict = memory["skill"]
        self.trials.append({
            "condition": condition, "trial": trial, "round": round_, "taskId": task, "skillId": skill,
            "reused": True, "attempt": memory["attempts"], "hadEnvFeedback": False, "hadSelfCritique": False,
            "selfVerdict": verdict, "execOk": ok})
        self.candidates.append({"step": len(self.candidates), "skillId": skill, "reused": True, "execOk": ok,
                                "code": code, "generation": None, "selfRationale": None})

    def files(self):
        def lines(rows):
            return "".join(json.dumps(row) + "\n" for row in rows).encode("utf-8")
        return {"trials.jsonl": lines(self.trials), "candidates.jsonl": lines(self.candidates),
                "summary.json": json.dumps(self.summary).encode("utf-8")}

    def run(self):
        return report.parse_run(self.files())

    def write(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True)
        for name, data in self.files().items():
            (directory / name).write_bytes(data)
        return directory


def verification_run():
    """Four trials of one self-verification cell; every task is generated once per trial."""
    r, cell = Recorder(), "sv1-ef0"
    r.new(cell, 0, 0, "t-first", "A", "PASS one")              # step 0: the first reply differs, the verdict does not
    r.new(cell, 0, 0, "t-flip", "B", "FAIL slow")              # step 1: the first verdict differs, usable program
    r.new(cell, 0, 0, "t-same", "C", "PASS same")
    r.new(cell, 0, 0, "t-once", "D", "PASS d")                 # sent once
    r.new(cell, 0, 0, "t-later", "E", "PASS e1")
    r.new(cell, 0, 0, "t-bad", "G", "PASS wrong", ok=False)    # step 5: the first verdict differs, unusable program
    r.reuse(cell, 0, 1, "t-same", ok=False)                    # step 6: the last execution of this skill fails
    for trial, later_code, later_reply in ((1, "E", "PASS e1"), (2, "F", "PASS f"), (3, "E", "PASS e2")):
        r.new(cell, trial, 0, "t-first", "A", "PASS two")
        r.new(cell, trial, 0, "t-flip", "B", "PASS fine")
        r.new(cell, trial, 0, "t-same", "C", "PASS same")
        r.new(cell, trial, 0, "t-later", later_code, later_reply)   # trial 2: other code; trial 3: another reply
        r.new(cell, trial, 0, "t-bad", "G", "FAIL right", ok=False)
    return r


def generation_run():
    r = Recorder()
    r.new("sv0-ef0", 0, 0, "w", "X", generation="same")
    r.new("sv0-ef0", 0, 1, "w", "X", generation="same")       # a second attempt without evidence: the task prompt
    r.new("sv0-ef1", 0, 0, "v", "X", ok=False)
    r.new("sv0-ef1", 0, 1, "v", "Z")                           # an informed retry with environment feedback
    for trial, first, critique, retry_code, retry in ((0, "g-first", "FAIL c1", "Y", "y1"),
                                                      (1, "g-later", "FAIL c1", "Y2", "y2"),
                                                      (2, "g-later", "FAIL c2", "Y", "y1")):
        r.new("sv1-ef0", trial, 0, "u", "X", critique, ok=False, generation=first)
        r.new("sv1-ef0", trial, 1, "u", retry_code, "PASS", generation=retry)   # an informed retry with a critique
    return r


def pair_of_runs():
    first, second, cell = Recorder(), Recorder(), "sv1-ef0"
    first.new(cell, 0, 0, "p", "X", "PASS a")
    first.new(cell, 0, 0, "q", "X", "PASS b")
    first.new(cell, 0, 0, "r", "X", "FAIL c")
    first.new(cell, 0, 0, "s", "X", "PASS d")
    first.reuse(cell, 0, 1, "p")
    first.reuse(cell, 0, 1, "q")
    first.new(cell, 0, 1, "r", "X2", "PASS")             # step 6: a verifier call in the first run only
    first.reuse(cell, 0, 1, "s")
    second.new(cell, 0, 0, "p", "X", "PASS a")           # the same request, verdict and text
    second.new(cell, 0, 0, "q", "X", "FAIL other")       # the same request, another verdict
    second.new(cell, 0, 0, "r", "Y", "PASS c")           # other code at the same step
    second.new(cell, 0, 0, "s", "X", "PASS d2")          # the same request and verdict, another text
    second.new(cell, 0, 1, "p", "X", "PASS a")           # steps 4 and 5: verifier calls in the second run only
    second.new(cell, 0, 1, "q", "X", "FAIL other")
    second.reuse(cell, 0, 1, "r")
    second.reuse(cell, 0, 1, "s")
    first.new(cell, 1, 0, "q", "X", "PASS b")            # step 8: the same request again, now with the same verdict
    second.new(cell, 1, 0, "q", "X", "PASS b")
    return first, second


class OccurrencesWithinARun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = report.analyse_run(verification_run().run())

    def test_first_reply_and_verdict(self):
        v = self.result["verification"]
        self.assertEqual((21, 7, 5), pick(v, "calls", "requests", "sentAtLeastTwice"))
        self.assertEqual((3, 2), pick(v, "firstReplyDiffers", "firstReplyDiffersAndVerdictDiffers"))
        self.assertEqual((14, 1), pick(v, "laterCalls", "laterCallsThatDiffer"))
        self.assertEqual((4, 2), pick(v, "withMoreThanOneReply", "withMoreThanOneVerdict"))
        self.assertEqual([
            {"task": "t-flip", "codeSha256Prefix": sha8("B"), "usable": True, "steps": [1, 8, 13, 18],
             "verdicts": "FPPP"},
            {"task": "t-bad", "codeSha256Prefix": sha8("G"), "usable": False, "steps": [5, 11, 16, 21],
             "verdicts": "PFFF"},
        ], v["verdictChanges"])
        self.assertEqual([("t-first", "abbb"), ("t-flip", "abbb"), ("t-later", "aab"), ("t-bad", "abbb")],
                         [pick(entry, "task", "replies") for entry in v["variedRequests"]])

    def test_later_replies_change_only_after_an_intervening_request(self):
        c = self.result["verification"]["consecutiveOccurrences"]
        self.assertEqual({"withoutInterveningRequest": {"pairs": 5, "changes": 3},
                          "withInterveningRequest": {"pairs": 0, "changes": 0}}, c["firstToSecond"])
        self.assertEqual({"withoutInterveningRequest": {"pairs": 8, "changes": 0},
                          "withInterveningRequest": {"pairs": 1, "changes": 1}}, c["fromSecondOn"])
        self.assertEqual([{"task": "t-later", "codeSha256Prefix": sha8("E"), "step": 20, "interveningRequest": True}],
                         c["changesFromSecondOn"])

    def test_a_request_for_another_task_does_not_intervene(self):
        r, cell = Recorder(), "sv1-ef0"
        for trial in range(3):
            r.new(cell, trial, 0, "a", "X", "PASS")
            r.new(cell, trial, 0, "b", f"code {trial}", "PASS")   # another task, with other code every time
        c = report.analyse_run(r.run())["verification"]["consecutiveOccurrences"]
        self.assertEqual({"pairs": 1, "changes": 0}, c["fromSecondOn"]["withoutInterveningRequest"])
        self.assertEqual({"pairs": 0, "changes": 0}, c["fromSecondOn"]["withInterveningRequest"])

    def test_first_reply_is_compared_with_the_most_frequent_later_reply(self):
        def counts(*replies):
            r = Recorder()
            for trial, reply in enumerate(replies):
                r.new("sv1-ef0", trial, 0, "a", "X", reply)
            v = report.analyse_run(r.run())["verification"]
            return pick(v, "firstReplyDiffers", "laterCallsThatDiffer", "withMoreThanOneReply")
        self.assertEqual((0, 1, 1), counts("PASS h", "PASS odd", "PASS h", "PASS h"))   # the second call is the odd one
        self.assertEqual((1, 1, 1), counts("PASS h", "PASS odd", "PASS odd", "PASS h"))
        self.assertEqual((1, 1, 1), counts("PASS h", "PASS odd", "PASS h"))             # a tie: the earlier later text
        self.assertEqual((1, 0, 1), counts("PASS h", "PASS odd"))
        self.assertEqual((0, 0, 0), counts("PASS h", "PASS h"))

    def test_a_verdict_change_without_a_text_change_is_listed_but_is_no_first_reply_difference(self):
        r = Recorder()
        for trial in range(3):
            r.new("sv1-ef0", trial, 0, "a", "X", "PASS same")
        r.trials[0]["selfVerdict"] = "fail"   # possible when replies are cut and the verdict was read further on
        v = report.analyse_run(r.run())["verification"]
        self.assertEqual((0, 0, 0, 1), pick(v, "firstReplyDiffers", "firstReplyDiffersAndVerdictDiffers",
                                            "withMoreThanOneReply", "withMoreThanOneVerdict"))
        self.assertEqual(["FPP"], [change["verdicts"] for change in v["verdictChanges"]])

    def test_the_first_verdict_is_compared_with_that_of_the_usual_later_reply(self):
        r = Recorder()
        for trial, reply in enumerate(("FAIL first", "PASS odd", "FAIL usual", "FAIL usual")):   # the second is odd
            r.new("sv1-ef0", trial, 0, "a", "X", reply)
        v = report.analyse_run(r.run())["verification"]
        self.assertEqual((1, 0, 1), pick(v, "firstReplyDiffers", "firstReplyDiffersAndVerdictDiffers",
                                         "withMoreThanOneVerdict"))

    def test_usable_follows_every_recorded_execution_of_the_program(self):
        executions = report.program_executions(verification_run().run()["steps"])
        self.assertEqual([True, False, None], [report.usable(executions, (task, report.sha256_text(code)))
                                               for task, code in (("t-flip", "B"), ("t-bad", "G"), ("t-same", "C"))])

    def test_static_relabelling(self):
        s = self.result["staticRelabelling"]
        self.assertEqual(21, s["skills"])
        # the skill that was reused counts by its last execution, which failed
        self.assertEqual({"tp": 15, "fp": 2, "fn": 1, "tn": 3}, s["observed"]["confusion"])
        self.assertEqual({"tp": 12, "fp": 5, "fn": 4, "tn": 0}, s["allFirstCall"]["confusion"])
        self.assertEqual({"tp": 16, "fp": 1, "fn": 0, "tn": 4}, s["allLaterCall"]["confusion"])
        self.assertEqual({"numerator": 2, "denominator": 5, "estimate": 0.4}, s["observed"]["falsePassRate"])
        self.assertEqual({"numerator": 1, "denominator": 16, "estimate": 0.0625}, s["observed"]["falseRejectRate"])
        self.assertEqual({"numerator": 5, "denominator": 5, "estimate": 1.0}, s["allFirstCall"]["falsePassRate"])
        self.assertEqual({"numerator": 0, "denominator": 16, "estimate": 0.0}, s["allLaterCall"]["falseRejectRate"])

    def test_a_rate_without_cases_has_no_estimate(self):
        r = Recorder()
        r.new("sv1-ef0", 0, 0, "a", "X", "PASS")
        s = report.analyse_run(r.run())["staticRelabelling"]
        self.assertEqual({"numerator": 0, "denominator": 0, "estimate": None}, s["observed"]["falsePassRate"])

    def test_later_call_verdict_with_two_calls_and_with_a_tie(self):
        r, cell = Recorder(), "sv1-ef0"
        r.new(cell, 0, 0, "a", "X", "FAIL one")
        r.new(cell, 1, 0, "a", "X", "PASS two")      # two calls: the later-call verdict is that of the second
        r.new(cell, 0, 0, "b", "Y", "PASS one")
        r.new(cell, 1, 0, "b", "Y", "FAIL two")
        r.new(cell, 2, 0, "b", "Y", "PASS three")    # a tie among the later calls: the verdict that occurs first
        s = report.analyse_run(r.run())["staticRelabelling"]
        self.assertEqual({"tp": 3, "fp": 0, "fn": 2, "tn": 0}, s["observed"]["confusion"])
        self.assertEqual({"tp": 3, "fp": 0, "fn": 2, "tn": 0}, s["allFirstCall"]["confusion"])
        self.assertEqual({"tp": 2, "fp": 0, "fn": 3, "tn": 0}, s["allLaterCall"]["confusion"])

    def test_generation_of_the_same_run(self):
        g = self.result["generation"]
        self.assertEqual((21, 6, 5, 0), pick(g, "calls", "requests", "sentAtLeastTwice", "firstOutputDiffers"))
        self.assertEqual((15, 1, 1), pick(g, "laterCalls", "laterCallsThatDiffer", "withMoreThanOneOutput"))
        self.assertEqual([{"task": "t-later", "kind": "plain", "calls": 4, "firstStep": 4, "outputs": "aaba"}],
                         g["variedRequests"])

    def test_a_tie_among_later_texts_goes_to_the_earlier_one(self):
        self.assertEqual("b", report.usual(["b", "a", "a", "b"]))
        self.assertEqual("a", report.usual(["b", "a", "a"]))
        self.assertEqual("abca", report.pattern(["x", "y", "z", "x"]))

    def test_stored_replies(self):
        keys = ("withFullText", "atTheLimitWithoutFullText", "textDifferencesAreALowerBound")
        self.assertEqual(dict(zip(keys, (0, 0, False))), self.result["storedReplies"])
        r = Recorder()
        r.new("sv1-ef0", 0, 0, "a", "X", "PASS " + "x" * 275)   # exactly 280 units and no full reply
        cut = report.analyse_run(r.run())["storedReplies"]
        self.assertEqual((0, 1, True), pick(cut, *keys))
        self.assertIn("lower bound", cut["statement"])
        r.new("sv1-ef0", 1, 0, "a", "X", "PASS " + "x" * 400)   # a run that stores full replies did not cut that one
        r.new("sv1-ef0", 2, 0, "a", "X", "PASS " + "x" * 401)
        full = report.analyse_run(r.run())
        self.assertEqual((2, 1, False), pick(full["storedReplies"], *keys))
        # the three replies share their first 280 units and differ only after them: the full texts are compared
        self.assertEqual((1, 1), pick(full["verification"], "firstReplyDiffers", "laterCallsThatDiffer"))


class GenerationRequests(unittest.TestCase):
    def test_task_prompts_and_informed_retries(self):
        g = report.analyse_run(generation_run().run())["generation"]
        kinds = ("calls", "requests", "sentAtLeastTwice", "firstOutputDiffers", "withMoreThanOneOutput")
        self.assertEqual((10, 6, 3, 2, 2), pick(g, *kinds))
        self.assertEqual(dict(zip(kinds, (6, 3, 2, 1, 1))), g["taskPrompts"])
        self.assertEqual(dict(zip(kinds, (4, 3, 1, 1, 1))), g["informedRetries"])

    def test_request_keys(self):
        calls = generation_run().run()["generationCalls"]
        self.assertEqual([("plain", "w"), ("plain", "w"), ("plain", "v"), ("informed", "v", True, None, "X"),
                          ("plain", "u"), ("informed", "u", False, "FAIL c1", "X"),
                          ("plain", "u"), ("informed", "u", False, "FAIL c1", "X"),
                          ("plain", "u"), ("informed", "u", False, "FAIL c2", "X")],
                         [call["request"] for call in calls])

    def test_flags_that_do_not_follow_from_the_earlier_steps_are_refused(self):
        r = generation_run()
        r.trials[-1]["hadSelfCritique"] = False
        with self.assertRaisesRegex(ValueError, "do not follow from the earlier steps"):
            r.run()

    def test_a_resumed_run_leaves_its_replayed_calls_out(self):
        r = Recorder(resumed=(2, 2, 0))
        r.new("sv0-ef0", 0, 0, "a", "X", generation="one")    # replayed from the interrupted run
        r.new("sv0-ef0", 0, 0, "b", "X", generation="b")      # replayed
        for trial in (1, 2, 3):
            r.new("sv0-ef0", trial, 0, "a", "X", generation="two")
        result = report.analyse_run(r.run())
        self.assertEqual((3, 1, 1, 0, 0), pick(result["generation"], "calls", "requests", "sentAtLeastTwice",
                                               "firstOutputDiffers", "withMoreThanOneOutput"))
        self.assertEqual(dict(zip(REPLAYED, (2, 2, 0))), result["resumed"])
        r.summary["resumed"]["replayedGenerations"] = 3
        with self.assertRaisesRegex(ValueError, "replayed calls"):
            r.run()

    def test_replayed_verifier_replies_are_left_out_and_block_the_relabelling(self):
        r = Recorder(resumed=(1, 1, 1))
        for trial, reply in enumerate(("PASS old", "PASS new", "PASS new")):
            r.new("sv1-ef0", trial, 0, "a", "X", reply)
        result = report.analyse_run(r.run())
        self.assertEqual((2, 0), pick(result["verification"], "calls", "firstReplyDiffers"))
        self.assertIsNone(result["staticRelabelling"])

    def test_the_inert_control_requests_each_task_once(self):
        r = Recorder(inert=True)
        r.new("sv1-ef0", 0, 0, "a", "X", "FAIL c", ok=False, generation="g")
        r.new("sv1-ef0", 0, 1, "a", "X", "FAIL c", ok=False, generation="g")   # the cached text, not a request
        r.new("sv1-ef0", 1, 0, "a", "X", "FAIL c", ok=False, generation="g")
        result = report.analyse_run(r.run())
        self.assertTrue(result["inert"])
        self.assertEqual((1, 1, 0), pick(result["generation"], "calls", "requests", "sentAtLeastTwice"))
        self.assertEqual((3, 1, 1), pick(result["verification"], "calls", "requests", "sentAtLeastTwice"))


class PairsAcrossRuns(unittest.TestCase):
    def test_same_request_is_kept_apart_from_different_code(self):
        first, second = pair_of_runs()
        p = report.pair_runs(first.run(), second.run())
        self.assertEqual(5, p["stepsWithAVerifierCallInBothRuns"])
        self.assertEqual({"first": 1, "second": 2}, p["verifierCallInOneRunOnly"])
        same = p["sameTaskAndCode"]
        self.assertEqual((4, 1, 2), pick(same, "pairs", "verdictDiffers", "replyTextDiffers"))
        self.assertEqual([{"task": "q", "codeSha256Prefix": sha8("X"), "pairs": 2, "verdictDiffers": 1,
                           "first": {"calls": 2, "verdicts": "PP", "usable": True},
                           "second": {"calls": 3, "verdicts": "FFP", "usable": True}}],
                         same["programsWithADifferentVerdict"])
        self.assertEqual({"pairs": 1, "verdictDiffers": 1}, p["differentCodeAtTheSameStep"])
        self.assertEqual(0, p["differentTaskAtTheSameStep"])
        self.assertFalse(p["textDifferencesAreALowerBound"])

    def test_another_task_at_the_same_step_is_no_pair(self):
        first, second = Recorder(), Recorder()
        first.new("sv1-ef0", 0, 0, "a", "X", "PASS")
        second.new("sv1-ef0", 0, 0, "b", "X", "FAIL")    # another task with the same code
        first.new("sv1-ef0", 0, 0, "c", "X", "PASS")
        second.new("sv1-ef0", 0, 0, "d", "Y", "FAIL")    # another task with other code
        p = report.pair_runs(first.run(), second.run())
        self.assertEqual((2, 0, 0, 2), (p["stepsWithAVerifierCallInBothRuns"], p["sameTaskAndCode"]["pairs"],
                                        p["differentCodeAtTheSameStep"]["pairs"], p["differentTaskAtTheSameStep"]))

    def test_replies_that_may_be_cut_are_compared_over_the_part_that_both_runs_store(self):
        def text_differs(first, second):
            p = report.pair_runs(first.run(), second.run())
            return p["sameTaskAndCode"]["replyTextDiffers"], p["textDifferencesAreALowerBound"]
        reply, other = "PASS " + "x" * 400, "PASS " + "z" * 400
        runs = {}
        for name, text in (("cut", reply), ("full", reply), ("late", reply[:300] + "y"), ("early", other)):
            runs[name] = Recorder()
            runs[name].new("sv1-ef0", 0, 0, "a", "X", text)
        del runs["cut"].candidates[0]["selfReply"]    # a run that keeps the first 280 units of a reply and no more
        self.assertEqual((0, True), text_differs(runs["cut"], runs["full"]))     # the same reply in both runs
        self.assertEqual((0, True), text_differs(runs["full"], runs["cut"]))
        self.assertEqual((0, True), text_differs(runs["cut"], runs["late"]))     # they differ after the stored part
        self.assertEqual((1, True), text_differs(runs["cut"], runs["early"]))    # they differ inside the stored part
        self.assertEqual((1, False), text_differs(runs["full"], runs["late"]))   # two full replies are compared whole
        self.assertEqual((0, False), text_differs(runs["full"], runs["full"]))

    def test_runs_with_other_request_settings_are_not_paired(self):
        first, second = pair_of_runs()
        second.summary["config"]["verifyTemplate"] = "B"
        with self.assertRaisesRegex(ValueError, "same recorded settings: verifyTemplate"):
            report.pair_runs(first.run(), second.run())


class Records(unittest.TestCase):
    def test_mismatched_records_are_refused(self):
        r = verification_run()
        r.candidates[3]["execOk"] = False
        with self.assertRaisesRegex(ValueError, "step 3: trial and candidate records disagree"):
            r.run()
        r = verification_run()
        r.candidates.pop()
        with self.assertRaisesRegex(ValueError, "22 trial records but 21 candidate records"):
            r.run()
        r = verification_run()
        r.candidates[3]["step"] = 4   # the candidate record names another step
        with self.assertRaisesRegex(ValueError, "step 3: trial and candidate records disagree"):
            r.run()

    def test_a_changed_code_within_a_skill_is_refused(self):
        r = verification_run()
        r.candidates[6]["code"] = "other"
        with self.assertRaisesRegex(ValueError, "code changed within a skill"):
            r.run()

    def test_a_new_skill_without_its_verifier_reply_is_refused(self):
        r = verification_run()
        r.candidates[0]["selfRationale"] = None
        with self.assertRaisesRegex(ValueError, "step 0: a verifier reply belongs"):
            r.run()

    def test_a_byte_order_mark_and_windows_line_ends_are_read(self):
        files = verification_run().files()
        marked = {name: b"\xef\xbb\xbf" + data.replace(b"\n", b"\r\n") for name, data in files.items()}
        plain, other = report.parse_run(files), report.parse_run(marked)
        self.assertEqual(report.analyse_run(plain), report.analyse_run(other))
        self.assertNotEqual(plain["fileSha256"], other["fileSha256"])   # the hashes are those of the bytes read


class Report(unittest.TestCase):
    def setUp(self):
        directory = temporary_directory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name).resolve()
        first, second = pair_of_runs()
        self.first = first.write(self.tmp / "private-archive" / "run-one")
        self.second = second.write(self.tmp / "private-archive" / "run-two")

    def call(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = report.main(list(arguments))
            except SystemExit as exit_:
                code = exit_.code
        return code, stdout.getvalue(), stderr.getvalue()

    def test_report_states_inputs_tool_and_what_was_not_done(self):
        out = self.tmp / "report.json"
        code, stdout, _ = self.call("--run", f"one={self.first}", "--reference", f"two={self.second}",
                                    "--pair", "one:two", "--exploratory", "one", "--note", "A note.",
                                    "--out", str(out))
        self.assertEqual(0, code)
        text = out.read_bytes().decode("utf-8")
        document = json.loads(text)
        self.assertEqual(report.encoded(document), text)
        self.assertEqual(sorted(document), list(document))                   # sorted keys at every level
        self.assertEqual(sorted(document["runs"]["one"]), list(document["runs"]["one"]))
        self.assertTrue(text.endswith("}\n") and not text.endswith("\n\n"))  # one trailing newline
        self.assertEqual(report.sha256_bytes(out.read_bytes()), json.loads(stdout)["sha256"])
        self.assertEqual((0, 0), pick(document, "candidateProgramsExecuted", "modelRequests"))
        self.assertEqual(report.sha256_bytes(Path(report.__file__).read_bytes()), document["tool"]["sha256"])
        self.assertEqual("experiments/rq-c/first_occurrence_report.py", document["tool"]["file"])
        self.assertEqual(report.DEFINITIONS, document["definitions"])
        self.assertEqual(["A note."], document["notes"])
        self.assertEqual(["one"], list(document["runs"]))                    # a reference is read for pairs only
        self.assertTrue(document["runs"]["one"]["exploratory"])
        self.assertEqual(["one -> two"], list(document["pairs"]))
        pair = document["pairs"]["one -> two"]
        self.assertEqual(("one", "two", 1),
                         pick(pair, "first", "second") + (pair["sameTaskAndCode"]["verdictDiffers"],))
        for label, directory, role in (("one", self.first, "run"), ("two", self.second, "reference")):
            entry = document["inputs"][label]
            self.assertEqual((directory.name, True, role), pick(entry, "directory", "private", "role"))
            self.assertEqual({name: report.sha256_bytes((directory / name).read_bytes())
                              for name in report.RECORD_FILES}, entry["sha256"])
            self.assertEqual("synthetic", entry["settings"]["model"])
        self.assertNotIn(str(self.tmp), text)                                # a private input leaves no path
        self.assertNotIn("private-archive", text)
        self.assertNotIn("PASS a", text)                                     # and no reply text

    def test_an_existing_report_is_not_overwritten(self):
        out = self.tmp / "report.json"
        arguments = ("--run", f"one={self.first}", "--out", str(out))
        self.assertEqual(0, self.call(*arguments)[0])
        written = out.read_bytes()
        code, _, stderr = self.call(*arguments)
        self.assertEqual(2, code)
        self.assertIn("is not overwritten", stderr)
        self.assertEqual(written, out.read_bytes())
        other = self.tmp / "other.json"
        other.write_text("kept", encoding="utf-8")
        self.assertEqual(2, self.call("--run", f"one={self.first}", "--out", str(other))[0])
        self.assertEqual("kept", other.read_text(encoding="utf-8"))
        with mock.patch.object(Path, "exists", return_value=False):   # a file that appears after the first check
            code, _, stderr = self.call("--run", f"one={self.first}", "--out", str(other))
        self.assertEqual(2, code)
        self.assertIn("exists", stderr.lower())
        self.assertEqual("kept", other.read_text(encoding="utf-8"))

    def test_without_out_the_report_goes_to_standard_output(self):
        code, stdout, _ = self.call("--run", f"one={self.first}")
        self.assertEqual(0, code)
        document = json.loads(stdout)
        self.assertEqual(report.SCHEMA, document["schema"])
        self.assertFalse(document["runs"]["one"]["exploratory"])
        self.assertEqual(([], {}), pick(document, "notes", "pairs"))

    def test_only_the_named_run_is_marked_exploratory(self):
        code, stdout, _ = self.call("--run", f"one={self.first}", "--run", f"two={self.second}", "--exploratory", "two")
        self.assertEqual(0, code)
        self.assertEqual({"one": False, "two": True},
                         {label: run["exploratory"] for label, run in json.loads(stdout)["runs"].items()})

    def test_wrong_labels_are_refused(self):
        for arguments in (("--run", f"one={self.first}", "--run", f"one={self.second}"),
                          ("--run", f"one={self.first}", "--pair", "one:two"),
                          ("--run", f"one={self.first}", "--reference", f"one={self.second}"),
                          ("--run", f"one={self.first}", "--exploratory", "two"),
                          ("--run", str(self.first)),
                          ("--reference", f"two={self.second}")):
            code, stdout, stderr = self.call(*arguments)
            self.assertEqual((2, ""), (code, stdout), arguments)
            self.assertTrue(stderr.strip(), arguments)

    def test_a_missing_run_directory_is_refused(self):
        code, _, stderr = self.call("--run", f"one={self.tmp / 'absent'}")
        self.assertEqual(2, code)
        self.assertIn("absent", stderr)


class Definitions(unittest.TestCase):
    def test_every_definition_of_the_report_is_in_the_module_text(self):
        text = " ".join(report.__doc__.split())
        for name, definition in report.DEFINITIONS.items():
            self.assertIn(f"{name}: {' '.join(definition.split())}", text)


class RetainedPublicRuns(unittest.TestCase):
    """The counts quoted from the public runs, recomputed from the retained records."""

    @classmethod
    def setUpClass(cls):
        directories = {label: HERE / path for label, path in PUBLIC_RUNS.items()}
        if not all((directory / name).is_file() for directory in directories.values() for name in report.RECORD_FILES):
            raise unittest.SkipTest("the retained public runs are not in this checkout")
        cls.document = json.loads(report.encoded(report.build_report(directories, pairs=PUBLIC_PAIRS)))

    def counts(self, prefix, layer, *keys):
        return [pick(self.document["runs"][f"{prefix}/{group}"][layer], *keys) for group in GROUPS]

    def test_verifier_requests(self):
        keys = ("calls", "sentAtLeastTwice", "firstReplyDiffers", "firstReplyDiffersAndVerdictDiffers")
        self.assertEqual([(770, 51, 13, 2), (852, 55, 0, 0), (750, 49, 4, 0)],
                         self.counts("archive", "verification", *keys))
        self.assertEqual([(759, 50, 10, 0), (857, 57, 2, 1), (756, 50, 6, 0)],
                         self.counts("host2-local", "verification", *keys))
        changes = {label: [pick(change, "task", "codeSha256Prefix", "usable", "verdicts")
                           for change in run["verification"]["verdictChanges"]]
                   for label, run in self.document["runs"].items()}
        self.assertEqual({
            "archive/second-family": [("math-fib", "db5d25bc", True, "F" + "P" * 21),
                                      ("parse-csv-line", "38c686cf", False, "PFF")],
            "host2-local/template-a": [("arr-flatten", "c66ca887", True, "P" + "F" * 9)],
        }, {label: found for label, found in changes.items() if found})

    def test_generation_requests(self):
        keys = ("firstOutputDiffers", "sentAtLeastTwice")
        self.assertEqual([(11, 57), (3, 65), (0, 54)], self.counts("archive", "generation", *keys))
        self.assertEqual([(9, 55), (2, 66), (3, 56)], self.counts("host2-local", "generation", *keys))

    def test_later_replies_are_stable_without_an_intervening_request(self):
        pairs = []
        for label, run in self.document["runs"].items():
            if label.startswith(("archive/", "host2-local/")):
                cell = run["verification"]["consecutiveOccurrences"]["fromSecondOn"]["withoutInterveningRequest"]
                self.assertEqual(0, cell["changes"], label)
                pairs.append(cell["pairs"])
        self.assertEqual([600, 588, 607, 602, 581, 602], pairs)

    def test_static_relabelling(self):
        def cells(label):
            relabelled = self.document["runs"][label]["staticRelabelling"]
            return [pick(relabelled[key]["confusion"], "tp", "fp", "fn", "tn")
                    for key in ("observed", "allFirstCall", "allLaterCall")]
        self.assertEqual([(672, 76, 1, 21), (651, 78, 22, 19), (673, 75, 0, 22)], cells("archive/second-family"))
        self.assertEqual([(643, 90, 67, 57), (652, 90, 58, 57), (642, 90, 68, 57)], cells("host2-local/template-a"))
        self.assertEqual([(654, 70, 68, 60)] * 3, cells("archive/template-a"))

    def test_pairs_of_the_host2_run_with_the_archive(self):
        found = [pick(pair["sameTaskAndCode"], "verdictDiffers", "pairs") for pair in self.document["pairs"].values()]
        self.assertEqual([(1, 563), (0, 792), (0, 716)], found)
        pair = self.document["pairs"]["archive/second-family -> host2-local/second-family"]
        self.assertEqual([("math-fib", "db5d25bc", 22, 1, "F" + "P" * 21, "P" * 22)],
                         [pick(program, "task", "codeSha256Prefix", "pairs", "verdictDiffers")
                          + (program["first"]["verdicts"], program["second"]["verdicts"])
                          for program in pair["sameTaskAndCode"]["programsWithADifferentVerdict"]])

    def test_main_run_and_inert_control(self):
        main, inert = self.document["runs"]["main"], self.document["runs"]["inert"]
        self.assertEqual((56, 5, 0), pick(main["verification"], "sentAtLeastTwice", "withMoreThanOneReply",
                                          "withMoreThanOneVerdict"))
        self.assertEqual((44, 7), pick(main["generation"]["taskPrompts"], "sentAtLeastTwice", "withMoreThanOneOutput"))
        self.assertEqual(dict(zip(REPLAYED, (124, 28, 0))), main["resumed"])
        self.assertTrue(main["storedReplies"]["textDifferencesAreALowerBound"])
        self.assertEqual((44, 0), pick(inert["generation"], "calls", "sentAtLeastTwice"))
        self.assertEqual((44, 1), pick(inert["verification"], "sentAtLeastTwice", "withMoreThanOneReply"))

    def test_public_inputs_are_recorded_by_their_repository_path(self):
        for label, path in PUBLIC_RUNS.items():
            entry = self.document["inputs"][label]
            self.assertEqual((f"experiments/rq-c/{path}", False, "run"), pick(entry, "directory", "private", "role"))
            self.assertEqual({name: report.sha256_bytes((HERE / path / name).read_bytes())
                              for name in report.RECORD_FILES}, entry["sha256"])

    def test_the_public_report_in_the_repository_is_reproduced(self):
        path = HERE / "first-occurrence-archive.json"
        if not path.is_file():
            self.skipTest("first-occurrence-archive.json is not in this checkout")
        stored = json.loads(path.read_text(encoding="utf-8"))
        for key in ("schema", "candidateProgramsExecuted", "modelRequests", "definitions", "inputs", "runs", "pairs"):
            self.assertEqual(stored[key], self.document[key], key)

    def test_department_reports_agree_with_the_public_runs_where_they_can(self):
        """Without the private records: one group per file, no private path, and the public side of every pair."""
        runs = {}
        for group in ("A", "B"):
            path = HERE / "department-20261124" / "analysis" / f"first-occurrence-{group}.json"
            if not path.is_file():
                self.skipTest(f"{path.name} is not in this checkout")
            text = path.read_text(encoding="utf-8")
            document = json.loads(text)
            self.assertEqual((0, 0), pick(document, "candidateProgramsExecuted", "modelRequests"))
            self.assertEqual([f"{group}/{name}" for name in GROUPS], list(document["runs"]))
            self.assertTrue(any("exploratory" in note for note in document["notes"]))
            for label, run in document["runs"].items():
                self.assertEqual(group == "B", run["exploratory"])
                self.assertEqual((RUN, True, "run"), pick(document["inputs"][label], "directory", "private", "role"))
            for fragment in ("/Volumes/", "/Users/", ":\\\\", "/home/", "/mnt/"):
                self.assertNotIn(fragment, text)
            self.assertEqual(len(GROUPS) if group == "A" else 2 * len(GROUPS), len(document["pairs"]))
            for pair in document["pairs"].values():
                label = pair["first"]
                self.assertEqual(f"{group}/{label.split('/')[1]}", pair["second"])
                entry = document["inputs"][label]
                self.assertEqual((f"experiments/rq-c/{PUBLIC_RUNS[label]}", False, "reference"),
                                 pick(entry, "directory", "private", "role"))
                self.assertEqual(self.document["inputs"][label]["sha256"], entry["sha256"])
                if label not in runs:
                    runs[label] = report.by_request(report.load_run(HERE / PUBLIC_RUNS[label])["verifierCalls"])
                for program in pair["sameTaskAndCode"]["programsWithADifferentVerdict"]:
                    calls = [call for (task, code), group_calls in runs[label].items() for call in group_calls
                             if task == program["task"] and code.startswith(program["codeSha256Prefix"])]
                    self.assertEqual(program["first"]["verdicts"], report.verdict_letters(calls))


if __name__ == "__main__":
    unittest.main()
