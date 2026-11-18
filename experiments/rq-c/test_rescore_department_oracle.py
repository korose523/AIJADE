"""Offline reference labels and synthetic transcript intake controls."""

from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

import launch_department_regeneration as launch
import rescore_department_oracle as oracle
import test_launch_department_regeneration as fixtures
from prepare_department_regeneration import REPO, encoded, prepare, sha
from summarize_department_regeneration import Skill
from test_prepare_department_regeneration import COMMIT, START


def outcome(status="PASSED", failed=(), **extra):
    return {"outcome": status, "failedCaseIndices": list(failed), **extra}


def transcript_for(manifest):
    return {
        "schema": oracle.TRANSCRIPT_SCHEMA, "binding": manifest["binding"],
        "manifestSha256": sha(encoded(manifest)), "reviewedEvaluatorReceiptSha256": "6" * 64,
        "groups": {group: {"captureFilesSha256": item["captureFilesSha256"], "programs": []}
                   for group, item in manifest["groups"].items()},
    }


class DepartmentOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worklist = prepare()
        cls.rule = oracle.rule_contract()

    def setUp(self):
        task = "str-to-camel"
        self.skills = {
            "f-first": Skill(("sv1-ef0", 0, task, "pass", "synthetic baseline failure"), 1, 0, False),
            "f-second": Skill(("sv1-ef1", 0, task, "fail", "synthetic baseline failure"), 1, 0, False),
            "c": Skill(("sv1-ef1", 0, task, "pass", "synthetic baseline pass"), 1, 1, True),
            "s": Skill(("sv0-ef0", 0, task, None, "synthetic skip label process"), 1, 1, True),
        }
        programs = oracle.program_population(self.skills)
        self.groups = {"control": (self.skills, programs)}
        self.manifest = {
            "binding": {"phaseReceiptSha256": "a" * 64, "ruleContractSha256": sha(encoded(self.rule))},
            "groups": {"control": {"captureFilesSha256": {"trials.jsonl": "b" * 64}, "programs": []}},
        }
        self.transcript = transcript_for(self.manifest)
        self.rows = self.transcript["groups"]["control"]["programs"]
        kept = self.rule["tasks"][task]["entryAndTestCaseIndices"]
        removed = next(i for i in self.rule["tasks"][task]["caseIndices"] if i not in kept)
        self.removed = removed
        self.rows.extend([
            {"taskId": task, "codeSha256": oracle.program_key(task, "synthetic baseline failure")[1],
             "status": "CAPTURED", "asRun": outcome("NO_CALLABLE"), "entry": outcome("FAILED_CASES", [removed]),
             "entryAndTest": outcome()},
            {"taskId": task, "codeSha256": oracle.program_key(task, "synthetic baseline pass")[1],
             "status": "CAPTURED", "asRun": outcome(), "entry": outcome(),
             "entryAndTest": outcome("FAILED_CASES", [kept[0]])},
            {"taskId": task, "codeSha256": oracle.program_key(task, "synthetic skip label process")[1],
             "status": "SKIPPED_ARCHIVE_HOST_FACILITY"},
        ])

    def score(self):
        return oracle.interpret_transcript(self.transcript, self.manifest, self.groups, self.rule)["control"]

    def test_reproduces_three_historical_runs_and_nine_label_tables(self):
        historical = oracle.archive_readback(self.worklist, self.rule)
        self.assertEqual({2000}, {task["timeoutMs"] for task in self.rule["tasks"].values()})
        self.assertEqual([69, 57, 49], [row["programs"] for row in historical.values()])
        self.assertEqual(
            [{"entry": 0, "additionalTestExclusion": 0}, {"entry": 1, "additionalTestExclusion": 3},
             {"entry": 1, "additionalTestExclusion": 0}],
            [row["promotions"] for row in historical.values()],
        )
        self.assertTrue(all(set(row["labels"]) == set(oracle.VARIANTS) for row in historical.values()))

    def test_explicit_variants_preserve_recorded_success_and_skips(self):
        result = self.score()
        self.assertEqual(3, result["programs"])
        self.assertEqual(1, result["historicalSkips"])
        labels = result["labels"]
        self.assertEqual({"tp": 1, "fp": 1, "fn": 0, "tn": 1}, labels["asRun"]["diagnostics"]["confusion"])
        self.assertEqual(labels["asRun"]["diagnostics"]["confusion"], labels["entry"]["diagnostics"]["confusion"])
        self.assertEqual({"tp": 2, "fp": 0, "fn": 1, "tn": 0}, labels["entryAndTest"]["diagnostics"]["confusion"])
        self.assertEqual(2, labels["asRun"]["distinct"]["candidates"])
        self.assertEqual(1, labels["asRun"]["distinct"]["falsePasses"])
        self.assertEqual({"NO_CALLABLE": 1, "PASSED": 1}, result["outcomesByVariant"]["asRun"])

    def test_historical_readback_allows_only_schema_specific_rounding(self):
        metric = {"n": 8, "estimate": 0.2, "taskBootstrapBca95": [0.1, 0.8]}
        reference = {"asRun": {"diagnostics": {"missRate": metric}, "clusteredMcNemar": {"clusteredP": 1e-14}}}
        for key, value, allowed in (
            ("taskBootstrapBca95", [0.1 + 4e-15, 0.8], True),
            ("taskBootstrapBca95", [0.1 + 2e-12, 0.8], False),
            ("taskBootstrapBca95", [0.1, "0.8"], False),
            ("estimate", 0.2 + 4e-15, False),
            ("n", 8.0, False),
        ):
            with self.subTest(key=key, value=value):
                actual = deepcopy(reference)
                actual["asRun"]["diagnostics"]["missRate"][key] = value
                self.assertIs(allowed, oracle.historical_labels_match(actual, reference))
        actual = deepcopy(reference)
        actual["asRun"]["clusteredMcNemar"]["clusteredP"] *= 1 + 5e-15
        self.assertTrue(oracle.historical_labels_match(actual, reference))
        actual["asRun"]["clusteredMcNemar"]["clusteredP"] = 2e-14
        self.assertIn("asRun.clusteredMcNemar.clusteredP: numeric delta",
                      oracle.historical_label_mismatch(actual, reference))

    def test_rejects_wrong_population_phase_and_capture_identity(self):
        for name in ("manifestSha256", "binding"):
            before = deepcopy(self.transcript[name])
            self.transcript[name] = {}
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "different inputs, rules or phase"):
                self.score()
            self.transcript[name] = before
        capture = self.transcript["groups"]["control"]
        before = deepcopy(capture["captureFilesSha256"])
        capture["captureFilesSha256"] = {}
        with self.assertRaisesRegex(ValueError, "capture hashes differ"):
            self.score()
        capture["captureFilesSha256"] = before
        self.rows.pop()
        with self.assertRaisesRegex(ValueError, "population or capture"):
            self.score()
        self.rows.append(deepcopy(self.rows[0]))
        with self.assertRaisesRegex(ValueError, "duplicated program"):
            self.score()

    def test_rejects_unsupported_skip_and_bad_judged_baseline(self):
        self.rows[0]["status"] = "SKIPPED_ARCHIVE_HOST_FACILITY"
        with self.assertRaisesRegex(ValueError, "skip does not match"):
            self.score()
        self.rows[0]["status"] = "CAPTURED"
        self.rows[0]["asRun"] = outcome()
        with self.assertRaisesRegex(ValueError, "disagrees on a judged skill"):
            self.score()

    def test_rejects_excluded_case_and_malformed_timeout(self):
        self.rows[0]["entryAndTest"] = outcome("FAILED_CASES", [self.removed])
        with self.assertRaisesRegex(ValueError, "excluded"):
            self.score()
        self.rows[0]["entryAndTest"] = outcome()
        self.assertEqual("TIMEOUT", oracle.checked_outcome(outcome("TIMEOUT", [0], timedOutCaseIndex=1), [0, 1, 2]))
        self.rows[0]["entry"] = outcome("TIMEOUT", [1], timedOutCaseIndex=1)
        with self.assertRaisesRegex(ValueError, "completed case prefix"):
            self.score()
        with self.assertRaisesRegex(ValueError, "duplicate object key"):
            oracle.decode_transcript(b'{"x":1,"x":2}')

    def test_manifest_and_score_cli_bind_a_simulated_completed_launcher(self):
        runtime = REPO / ".runtime"
        runtime.mkdir(exist_ok=True)
        with TemporaryDirectory(prefix="p2-r-oracle-intake-controls-", dir=runtime) as temp:
            root = Path(temp).resolve()
            bundle = root / "regeneration"
            instrument = fixtures.FixtureRuntime(self.worklist, {})
            approval = {"sourceCommit": COMMIT, "ollamaUrl": "http://synthetic.invalid:11434",
                        "ollamaVersion": fixtures.VERSION, "logHistorySince": launch.stamp(START),
                        "notAfter": launch.stamp(fixtures.END), "host": fixtures.HOST,
                        "build": {"rqcDll": "inert.dll", "files": {"inert.dll": "3" * 64}}}
            tools = {name: root / name for name in ("dotnet", "rqcDll", "substrateDll")}
            qualification = {
                "sha256": "4" * 64,
                "finalLogs": fixtures.capture_raw(START, START + timedelta(seconds=2),
                                                 [("system", {"id": "historical", "at": launch.stamp(START + timedelta(seconds=1)),
                                                              "record": "synthetic event"})]),
            }
            phase = launch.perform("regeneration", bundle, approval, "5" * 64, tools,
                                   self.worklist, instrument, qualification)
            self.assertEqual("REGENERATION_EVIDENCE_COMPLETE", phase["status"])
            raw = (bundle / "phase-result.json").read_bytes()
            pin = sha(raw)
            manifest, bound_groups = oracle.accepted_population(bundle, pin, self.worklist, self.rule)
            self.assertEqual(pin, manifest["binding"]["phaseReceiptSha256"])
            self.assertEqual(COMMIT, manifest["binding"]["sourceCommit"])
            self.assertEqual([69, 57, 49], [len(row["programs"]) for row in manifest["groups"].values()])
            self.assertEqual([1519, 1602, 1500], [len(skills) for skills, _ in bound_groups.values()])
            self.assertTrue(all(set(row) == {"taskId", "codeSha256", "historicalSkipApplies"}
                                for group in manifest["groups"].values() for row in group["programs"]))
            with self.assertRaisesRegex(ValueError, "file identity differs"):
                oracle.accepted_population(bundle, "8" * 64, self.worklist, self.rule)
            self.assertEqual(raw, (bundle / "phase-result.json").read_bytes())

            transcript = transcript_for(manifest)
            evaluator = root / "synthetic-evaluator-receipt.json"
            evaluator.write_bytes(encoded({"scope": "synthetic operator receipt control"}))
            transcript["reviewedEvaluatorReceiptSha256"] = sha(evaluator.read_bytes())
            for group, (_, programs) in bound_groups.items():
                for (task, digest), states in programs.items():
                    row = {"taskId": task, "codeSha256": digest, "status": "CAPTURED"}
                    terminal = "PASSED" if states[0].last_execution_ok else "NO_CALLABLE"
                    row.update((variant, outcome(terminal)) for variant in oracle.VARIANTS)
                    transcript["groups"][group]["programs"].append(row)
            retained = root / "synthetic-replay-transcript.json"
            retained.write_bytes(encoded(transcript))
            command = [sys.executable, "-B", str(Path(oracle.__file__)), "score", "--regeneration-bundle", str(bundle),
                       "--phase-receipt-sha256", pin, "--replay-transcript", str(retained),
                       "--replay-transcript-sha256", sha(retained.read_bytes()), "--evaluator-receipt", str(evaluator)]
            process = subprocess.run(command, cwd=REPO, capture_output=True)
            self.assertEqual(0, process.returncode, process.stderr)
            report = json.loads(process.stdout)
            self.assertEqual("EXPLORATORY_REPLAY_TRANSCRIPT_SCORED", report["scope"])
            self.assertEqual(0, report["candidateExecutionsByReport"])
            self.assertEqual(0, report["formalRunsStartedByReport"])
            self.assertEqual(sha(encoded(manifest)), report["manifestSha256"])
            self.assertEqual(sha(evaluator.read_bytes()), report["reviewedEvaluatorReceiptSha256"])
            self.assertEqual([69, 57, 49],
                             [report["retainedArchiveGroups"][name]["programs"] for name in manifest["groups"]])
            self.assertEqual([69, 57, 49],
                             [report["groups"][name]["programs"] for name in manifest["groups"]])
            for artifact in (retained, evaluator):
                with self.subTest(pin=artifact.name):
                    original = artifact.read_bytes()
                    artifact.write_bytes(original + b"\n")
                    rejected = subprocess.run(command, cwd=REPO, capture_output=True)
                    self.assertEqual(2, rejected.returncode)
                    self.assertIn(b"file identity differs", rejected.stderr)
                    self.assertEqual(b"", rejected.stdout)
                    artifact.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
