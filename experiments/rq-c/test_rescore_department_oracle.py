"""Offline reference labels and synthetic transcript intake controls."""

from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

import department_oracle_evidence as evidence
import launch_department_regeneration as launch
import rescore_department_oracle as oracle
import test_launch_department_regeneration as fixtures
from prepare_department_regeneration import REPO, encoded, prepare, sha
from summarize_department_regeneration import Skill
from test_prepare_department_regeneration import COMMIT, START


def outcome(status="PASSED", failed=(), **extra):
    return {"outcome": status, "failedCaseIndices": list(failed), **extra}


def observed_cases(*cases):
    return {"status": "CASE_RESULTS", "cases": [{"caseIndex": index, "result": result}
                                              for index, result in cases]}


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
            evidence.decode_evidence(b'{"x":1,"x":2}')
        with self.assertRaisesRegex(ValueError, "non-finite JSON"):
            evidence.decode_evidence(b'{"x":NaN}')

    def test_observed_case_results_distinguish_all_terminal_outcomes(self):
        derive = evidence.derive_case_outcome
        cases = [1, 3, 4]
        self.assertEqual(outcome(), derive(observed_cases((1, "PASS"), (3, "PASS"), (4, "PASS")), cases))
        self.assertEqual(outcome("FAILED_CASES", [1, 4]),
                         derive(observed_cases((1, "FAIL"), (3, "PASS"), (4, "FAIL")), cases))
        self.assertEqual(outcome("TIMEOUT", [1], timedOutCaseIndex=3),
                         derive(observed_cases((1, "FAIL"), (3, "TIMEOUT")), cases))
        for status in ("NO_CALLABLE", "SETUP_ERROR"):
            self.assertEqual(outcome(status), derive({"status": status, "cases": []}, cases))
            with self.assertRaisesRegex(ValueError, "cannot have case observations"):
                derive({"status": status, "cases": [{"caseIndex": 1, "result": "FAIL"}]}, cases)

    def test_observed_case_results_reject_partial_ambiguous_or_excluded_evidence(self):
        for cases, message in (
            (observed_cases(), "stopped before"),
            (observed_cases((1, "PASS")), "stopped before"),
            (observed_cases((1, "TIMEOUT"), (3, "PASS")), "timeout must be the final"),
            (observed_cases((1, "PASS"), (2, "FAIL")), "exact retained order"),
            (observed_cases((1, "PASS"), (1, "FAIL")), "exact retained order"),
            (observed_cases((True, "FAIL")), "exact retained order"),
            (observed_cases((1, "ERROR")), "unknown case observation result"),
        ):
            with self.subTest(cases=cases), self.assertRaisesRegex(ValueError, message):
                evidence.derive_case_outcome(cases, [1, 3, 4])

    def test_observed_programs_preserve_exclusions_and_independent_variants(self):
        task = "str-to-camel"
        digest, skip_digest = "a" * 64, "b" * 64
        full = self.rule["tasks"][task]["caseIndices"]
        retained = self.rule["tasks"][task]["entryAndTestCaseIndices"]
        pinned = [
            {"taskId": task, "codeSha256": digest, "historicalSkipApplies": False},
            {"taskId": task, "codeSha256": skip_digest, "historicalSkipApplies": True},
        ]
        skipped = {"taskId": task, "codeSha256": skip_digest, "status": evidence.SKIPPED}
        row = {"taskId": task, "codeSha256": digest, "status": "CAPTURED",
               "asRun": {"status": "NO_CALLABLE", "cases": []},
               "entry": observed_cases(*[(index, "FAIL" if index == self.removed else "PASS")
                                         for index in full]),
               "entryAndTest": observed_cases(*[(index, "PASS") for index in retained])}
        actual = evidence.derive_programs([skipped, row], pinned, self.rule)
        self.assertEqual([{"taskId": task, "codeSha256": digest, "status": "CAPTURED",
                           "asRun": outcome("NO_CALLABLE"), "entry": outcome("FAILED_CASES", [self.removed]),
                           "entryAndTest": outcome()}, skipped], actual)
        independent = dict(row, entry=observed_cases(*[(index, "PASS") for index in full]),
                           entryAndTest=observed_cases((retained[0], "TIMEOUT")))
        observed = evidence.derive_programs([independent, skipped], pinned, self.rule)[0]
        self.assertEqual(outcome(), observed["entry"])
        self.assertEqual(outcome("TIMEOUT", timedOutCaseIndex=retained[0]), observed["entryAndTest"])
        with self.assertRaisesRegex(ValueError, "exact retained order"):
            evidence.derive_programs([dict(row, entryAndTest=observed_cases((self.removed, "FAIL"))), skipped],
                                     pinned, self.rule)
        with self.assertRaisesRegex(ValueError, "observed skip differs"):
            evidence.derive_programs([row, dict(skipped, status="CAPTURED")], pinned, self.rule)
        with self.assertRaisesRegex(ValueError, "missing or unexpected"):
            evidence.derive_programs([row, dict(skipped, asRun=observed_cases())], pinned, self.rule)
        with self.assertRaisesRegex(ValueError, "unknown or duplicate"):
            evidence.derive_programs([dict(row, codeSha256="c" * 64), skipped], pinned, self.rule)
        with self.assertRaisesRegex(ValueError, "unknown or duplicate"):
            evidence.derive_programs([row, row], pinned, self.rule)
        with self.assertRaisesRegex(ValueError, "population differs"):
            evidence.derive_programs([row], pinned, self.rule)

    def test_manifest_produce_and_score_cli_bind_a_simulated_completed_launcher(self):
        runtime = REPO / ".runtime"
        runtime.mkdir(exist_ok=True)
        with TemporaryDirectory(prefix="p2-r-oracle-intake-controls-", dir=runtime) as temporary:
            self.check_synthetic_cli_flow(Path(temporary).resolve())

    def check_synthetic_cli_flow(self, root):
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
        phase = launch.perform("regeneration", bundle, approval, "5" * 64, tools, self.worklist, instrument, qualification)
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

        command = [sys.executable, "-B", str(Path(oracle.__file__))]
        phase_args = ["--regeneration-bundle", str(bundle), "--phase-receipt-sha256", pin]

        def invoke(action, arguments):
            return subprocess.run([*command, action, *phase_args, *arguments], cwd=REPO, capture_output=True)

        def write_report(action, arguments, artifact):
            process = invoke(action, [*arguments, "--out", str(artifact)])
            self.assertEqual(0, process.returncode, process.stderr)
            self.assertEqual(process.stdout, artifact.read_bytes())
            return json.loads(process.stdout)

        manifest_path = root / "synthetic-replay-manifest.json"
        manifest_doc = write_report("manifest", [], manifest_path)
        self.assertEqual(manifest, manifest_doc["manifest"])
        manifest_hash = sha(manifest_path.read_bytes())
        observed, groups = self.synthetic_observations(manifest_doc, manifest_hash, bound_groups)
        observations = root / "synthetic-observations.json"
        observations.write_bytes(encoded(observed))
        observations_hash = sha(observations.read_bytes())
        evaluator_body = {
            "schema": evidence.EVALUATOR_SCHEMA, "evidenceScope": observed["evidenceScope"],
            "binding": observed["binding"], "manifestSha256": observed["manifestSha256"],
            "manifestFileSha256": manifest_hash, "observationsFileSha256": observations_hash,
            "referenceReplayEngineSha256": self.rule["referenceReplayEngineSha256"], "groups": groups,
            "evaluatorIdentity": {name: sha(f"synthetic evaluator {name}".encode()) for name in (
                "artifactSha256", "runtimeSha256", "invocationContractSha256", "environmentSha256")},
        }
        evaluator = root / "synthetic-evaluator-receipt.json"
        evaluator.write_bytes(encoded(evaluator_body))
        input_args = ["--replay-manifest", str(manifest_path), "--replay-manifest-sha256", manifest_hash,
                      "--observations", str(observations), "--observations-sha256", observations_hash,
                      "--evaluator-receipt", str(evaluator), "--evaluator-receipt-sha256", sha(evaluator.read_bytes())]
        mode_args = ["--evidence-mode", "synthetic"]
        retained = root / "synthetic-replay-transcript.json"
        transcript = write_report("produce", [*input_args, *mode_args], retained)
        self.assertEqual(evidence.TRANSCRIPT_SCHEMA, transcript["schema"])
        self.assertEqual("SYNTHETIC_FIXTURE", transcript["evidenceScope"])
        transcript_args = ["--replay-transcript", str(retained), "--replay-transcript-sha256", sha(retained.read_bytes())]
        scored = root / "synthetic-score-report.json"
        report = write_report("score", [*input_args, *mode_args, *transcript_args], scored)
        self.assertEqual("SYNTHETIC_REPLAY_TRANSCRIPT_SCORED", report["scope"])
        self.assertEqual(0, report["candidateExecutionsByReport"])
        self.assertEqual(0, report["formalRunsStartedByReport"])
        self.assertEqual(sha(encoded(manifest)), report["manifestSha256"])
        self.assertEqual(sha(evaluator.read_bytes()), report["reviewedEvaluatorReceiptSha256"])
        self.assertEqual([69, 57, 49],
                         [report["retainedArchiveGroups"][name]["programs"] for name in manifest["groups"]])
        self.assertEqual([69, 57, 49], [report["groups"][name]["programs"] for name in manifest["groups"]])
        outcomes = {outcome for group in report["groups"].values()
                    for counts in group["outcomesByVariant"].values() for outcome in counts}
        self.assertEqual(oracle.OUTCOMES, outcomes)
        for name, item in transcript["groups"].items():
            projected = next(row for row in item["programs"]
                             if row["status"] == "CAPTURED" and row["entry"]["outcome"] == "TIMEOUT")
            timed_case = self.rule["tasks"][projected["taskId"]]["caseIndices"][1]
            self.assertEqual(outcome("TIMEOUT", timedOutCaseIndex=timed_case), projected["entry"])
            self.assertEqual(outcome("NO_CALLABLE"), projected["asRun"])
            self.assertEqual(outcome(), projected["entryAndTest"])
            scored_group = report["groups"][name]
            self.assertEqual(1, scored_group["outcomesByVariant"]["entry"]["TIMEOUT"])
            tables = scored_group["labels"]
            before = tables["asRun"]["diagnostics"]["confusion"]
            self.assertEqual(before, tables["entry"]["diagnostics"]["confusion"])
            after = tables["entryAndTest"]["diagnostics"]["confusion"]
            self.assertGreater(before["fp"], after["fp"])
            self.assertEqual(before["fp"] - after["fp"], after["tp"] - before["tp"])

        group = next(iter(observed["groups"]))
        changed = deepcopy(observed)
        changed["groups"][group]["captureFilesSha256"]["trials.jsonl"] = "1" * 64
        changed_raw = encoded(changed)
        repinned = encoded(dict(evaluator_body, observationsFileSha256=sha(changed_raw)))
        with self.assertRaisesRegex(ValueError, "observed capture hashes differ"):
            evidence.produce_transcript(manifest_doc, manifest_path.read_bytes(), changed_raw, repinned,
                                        observed["evidenceScope"])

        def reject(label, action, arguments, message):
            rejected = invoke(action, arguments)
            self.assertEqual(2, rejected.returncode, rejected.stderr)
            self.assertIn(message, rejected.stderr)
            self.assertEqual(b"", rejected.stdout)
            return {"control": label, "exitCode": rejected.returncode, "stderr": rejected.stderr.decode().strip()}

        failures = [reject("synthetic-in-external-mode", "score", [*input_args, *transcript_args],
                           b"external replay requires the complete operator-reviewed case capture")]
        for artifact in (manifest_path, observations, evaluator, retained):
            with self.subTest(pin=artifact.name):
                original = artifact.read_bytes()
                artifact.write_bytes(original + b"\n")
                try:
                    failures.append(reject(f"changed-{artifact.stem}", "score", [*input_args, *mode_args, *transcript_args],
                                           b"file identity differs"))
                finally:
                    artifact.write_bytes(original)
        forged = root / "synthetic-repinned-transcript.json"
        forged.write_bytes(encoded(dict(transcript, observationsFileSha256="1" * 64)))
        failures.append(reject("repinned-transcript-differs", "score",
                               [*input_args, *mode_args, "--replay-transcript", str(forged),
                                "--replay-transcript-sha256", sha(forged.read_bytes())],
                               b"reviewed transcript differs from the observed case results"))
        unbound = root / "synthetic-repinned-evaluator.json"
        unbound.write_bytes(encoded(dict(evaluator_body, observationsFileSha256="1" * 64)))
        failures.append(reject("repinned-unbound-receipt", "produce",
                               [*input_args[:-4], *mode_args, "--evaluator-receipt", str(unbound),
                                "--evaluator-receipt-sha256", sha(unbound.read_bytes())],
                               b"evaluator receipt does not bind"))
        (root / "synthetic-refusal-controls.json").write_bytes(encoded(failures))
        return report

    def synthetic_observations(self, manifest_doc, manifest_hash, bound_groups):
        manifest = manifest_doc["manifest"]
        observed = {"schema": evidence.OBSERVATIONS_SCHEMA, "evidenceScope": "SYNTHETIC_FIXTURE",
                    "binding": manifest["binding"], "manifestSha256": manifest_doc["manifestSha256"],
                    "manifestFileSha256": manifest_hash, "groups": {}}
        groups = {}
        for name, item in manifest["groups"].items():
            programs = bound_groups[name][1]
            rows = []
            for record in item["programs"]:
                task, digest = record["taskId"], record["codeSha256"]
                row = {"taskId": task, "codeSha256": digest,
                       "status": evidence.SKIPPED if record["historicalSkipApplies"] else "CAPTURED"}
                if not record["historicalSkipApplies"]:
                    for variant in evidence.VARIANTS:
                        index_key = "entryAndTestCaseIndices" if variant == "entryAndTest" else "caseIndices"
                        cases = self.rule["tasks"][task][index_key]
                        row[variant] = (observed_cases(*[(index, "PASS") for index in cases])
                                        if programs[task, digest][0].last_execution_ok
                                        else {"status": "NO_CALLABLE", "cases": []})
                rows.append(row)
            # Script a timeout and a third-variant pass for a recorded verifier false pass.
            changed = next(row for row in rows if row["status"] == "CAPTURED"
                           and len(self.rule["tasks"][row["taskId"]]["caseIndices"]) >= 2
                           and any(skill.identity[3] == "pass" and not skill.last_execution_ok
                                   for skill in programs[row["taskId"], row["codeSha256"]]))
            task = self.rule["tasks"][changed["taskId"]]
            first, second = task["caseIndices"][:2]
            changed["entry"] = observed_cases((first, "PASS"), (second, "TIMEOUT"))
            changed["entryAndTest"] = observed_cases(*[(index, "PASS") for index in task["entryAndTestCaseIndices"]])
            case_failure = next(row for row in rows if row is not changed and row["status"] == "CAPTURED")
            kept = self.rule["tasks"][case_failure["taskId"]]["entryAndTestCaseIndices"]
            case_failure["entry"] = {"status": "SETUP_ERROR", "cases": []}
            case_failure["entryAndTest"] = observed_cases(*[(index, "FAIL") for index in kept])
            observed["groups"][name] = {"captureFilesSha256": item["captureFilesSha256"], "programs": rows}
            groups[name] = {"captureFilesSha256": item["captureFilesSha256"], "programCount": len(rows)}
        return observed, groups


if __name__ == "__main__":
    unittest.main()
