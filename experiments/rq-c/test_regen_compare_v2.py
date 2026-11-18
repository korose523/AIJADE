"""Offline regression tests for the P2-R comparison instrument."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from regen_compare_v2 import CONDITIONS


HERE = Path(__file__).resolve().parent
ARCHIVES = {
    "family-gpu": (
        "56e40a5e54d6a3bbe2884d25bf5e6049d2dd4ecb5c338a177764d709766b4121",
        "9f53d82b6e38ff5286fc62c062cc54579d7a6e8fa9a1b1232f84bea486ce4d61",
    ),
    "template-gpu/A": (
        "73dfd090ff3410f1a24e62ff75ab69b0bab90a01fbedfe502ad285f7b6b18436",
        "928a99838f7b57696c2e7fe4731bc3b2890b16c2ed7ef9461d1ad3dae61d2ae3",
    ),
    "template-gpu/B": (
        "fc76a3cc69ed351108052c68772902a03b936aa728c28542a0de3ad74c7b07c0",
        "fd4b5408eb2592a9322728e23b51ad669f82bbdcdc8d7b5365636a3ef9439be2",
    ),
}


def fixture_rows(trials):
    output = []
    for condition in CONDITIONS:
        for trial in range(trials):
            for task in ("task-one", "task-two"):
                skill = f"{condition}-t{trial}-r0-{task}"
                verified = condition.startswith("sv1-")
                candidate = {
                    "skillId": skill, "generation": "synthetic generation", "code": "synthetic code",
                    "selfRationale": "synthetic rationale" if verified else None,
                    "reused": False, "execOk": True,
                }
                if verified:
                    candidate["selfReply"] = "synthetic full reply"
                output.append((
                    {"condition": condition, "trial": trial, "round": 0, "taskId": task,
                     "skillId": skill, "selfVerdict": "pass" if verified else None,
                     "execOk": True, "reused": False},
                    candidate,
                ))
    return output


def write_fixture(path, trials, rows, *, summary=True):
    path.mkdir()
    with (path / "trials.jsonl").open("w", encoding="utf-8") as trial_file, (
        path / "candidates.jsonl"
    ).open("w", encoding="utf-8") as candidate_file:
        for index, (trial, candidate) in enumerate(rows):
            trial_file.write(json.dumps(trial) + "\n")
            candidate_file.write(json.dumps({"step": index, **candidate}) + "\n")
    if summary:
        (path / "summary.json").write_text(json.dumps({
            "config": {
                "trials": trials, "rounds": 1, "tasks": 2, "seed": 42,
                "backend": "ollama", "domain": "executable", "model": "synthetic-model",
                "pCorrect": 0.5, "pruneThreshold": 0.5, "pruneMinCalls": 3,
                "maxReplyTokens": 4096, "numCtx": 4096,
            },
            "sampling": {
                "mode": "live", "model": "synthetic-model", "temperature": 0,
                "seed": 3759066737, "modelDigest": "a" * 64, "ollamaVersion": "synthetic-1",
            },
            "nExecutions": trials * 2 * len(CONDITIONS),
            "nSkills": len({trial["skillId"] for trial, _ in rows}),
            "conditions": list(CONDITIONS),
        }), encoding="utf-8")


def edit_summary(directory, section, field, value):
    path = directory / "summary.json"
    data = json.loads(path.read_bytes())
    data[section][field] = value
    path.write_text(json.dumps(data), encoding="utf-8")


class RegenerationComparisonTests(unittest.TestCase):
    def setUp(self):
        runtime = HERE.parents[1] / ".runtime"
        runtime.mkdir(exist_ok=True)
        workspace = tempfile.TemporaryDirectory(prefix="p2-compare-test-", dir=runtime)
        self.addCleanup(workspace.cleanup)
        self.workspace = Path(workspace.name)
        self.archive = self.workspace / "archived"
        self.regenerating = self.workspace / "regenerated"
        write_fixture(self.archive, 2, fixture_rows(2))

    def compare(self, *args, archived=None, regenerated=None):
        return subprocess.run(
            [sys.executable, "-B", "-I", str(HERE / "regen_compare_v2.py"),
             "--archived", str(self.archive if archived is None else archived),
             "--regenerated", str(self.regenerating if regenerated is None else regenerated),
             *args],
            capture_output=True, encoding="utf-8", check=False,
        )

    def test_all_three_pinned_archives_are_complete_identical_to_themselves(self):
        for group, (trials_sha, candidates_sha) in ARCHIVES.items():
            with self.subTest(group=group):
                directory = HERE / group / "rq-c-s42-ollama-t30-r5"
                result = self.compare(archived=directory, regenerated=directory)
                self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
                report = json.loads(result.stdout)
                self.assertEqual("IDENTICAL", report["status"])
                self.assertEqual(trials_sha, report["inputs"]["archived"]["trials.jsonl"])
                self.assertEqual(candidates_sha, report["inputs"]["archived"]["candidates.jsonl"])
                self.assertEqual([1800] * 4,
                                 [report["conditions"][c]["identicalPrefixSteps"] for c in CONDITIONS])

    def test_no_rows_never_reports_identity(self):
        write_fixture(self.regenerating, 2, [], summary=False)
        result = self.compare()
        self.assertEqual(result.returncode, 2)
        report = json.loads(result.stdout)
        self.assertEqual("INCOMPLETE", report["status"])
        self.assertFalse(report["identical"])
        self.assertEqual([0] * 4, [report["conditions"][c]["sharedSteps"] for c in CONDITIONS])

    def test_truncated_rows_remain_incomplete_even_without_observed_divergence(self):
        write_fixture(self.regenerating, 2, fixture_rows(2)[:-1], summary=False)
        result = self.compare()
        self.assertEqual(result.returncode, 2)
        report = json.loads(result.stdout)
        self.assertEqual("INCOMPLETE", report["status"])
        row = report["conditions"][CONDITIONS[-1]]
        self.assertIsNone(row["firstDivergence"])
        self.assertEqual(3, row["identicalPrefixSteps"])
        self.assertFalse(report["identical"])

    def test_stale_success_summary_does_not_accept_a_truncated_run(self):
        write_fixture(self.regenerating, 2, fixture_rows(2)[:-1])
        result = self.compare()
        self.assertEqual(result.returncode, 2)
        report = json.loads(result.stdout)
        self.assertEqual("INVALID", report["status"])
        self.assertIn("summary.nExecutions", report["error"])

    def test_missing_condition_is_incomplete(self):
        write_fixture(self.regenerating, 2, fixture_rows(2)[4:], summary=False)
        result = self.compare()
        self.assertEqual(result.returncode, 2)
        report = json.loads(result.stdout)
        self.assertEqual("INCOMPLETE", report["status"])
        self.assertEqual(0, report["conditions"][CONDITIONS[0]]["regeneratedSteps"])
        self.assertEqual(4, report["conditions"][CONDITIONS[1]]["regeneratedSteps"])

    def test_qualification_prefix_is_explicit_and_has_its_own_expected_count(self):
        write_fixture(self.regenerating, 1, fixture_rows(1))
        default = self.compare()
        self.assertEqual(default.returncode, 2)
        self.assertEqual("INVALID", json.loads(default.stdout)["status"])
        result = self.compare("--qualification-trials", "1")
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual("QUALIFICATION_TRIALS", report["scope"])
        self.assertEqual(2, report["population"]["archivedTrials"])
        self.assertEqual(1, report["population"]["regeneratedTrials"])
        self.assertEqual([2] * 4,
                         [report["conditions"][c]["identicalPrefixSteps"] for c in CONDITIONS])

    def test_changed_full_reply_is_observed_with_equal_rationale(self):
        rows = fixture_rows(2)
        rows[9][1]["selfReply"] = "different full reply"
        rows[10][1]["generation"] = "different generation after the divergence"
        write_fixture(self.regenerating, 2, rows)
        result = self.compare()
        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual("DIFFERENT", report["status"])
        self.assertTrue(report["complete"])
        first = report["conditions"]["sv1-ef0"]["firstDivergence"]
        self.assertEqual(1, first["step"])
        self.assertEqual(["verifierReply"], first["differs"])

    def test_configuration_and_sampler_are_bound_to_the_records(self):
        for name, section, field, value, expected in (
            ("context", "config", "numCtx", 2048, "configuration differs: numCtx"),
            ("template", "config", "verifyTemplate", "B", "configuration differs: verifyTemplate"),
            ("null-setting", "config", "pruneThreshold", None, "config.pruneThreshold"),
            ("seed", "sampling", "seed", 1, "sampling.seed must match"),
            ("digest", "sampling", "modelDigest", "b" * 64, "sampling.modelDigest differs"),
        ):
            with self.subTest(name=name):
                directory = self.workspace / name
                write_fixture(directory, 2, fixture_rows(2))
                edit_summary(directory, section, field, value)
                result = self.compare(regenerated=directory)
                self.assertEqual(2, result.returncode)
                report = json.loads(result.stdout)
                self.assertEqual("INVALID", report["status"])
                self.assertIn(expected, report["error"])

    def test_prefix_still_rejects_configuration_mismatch(self):
        write_fixture(self.regenerating, 1, fixture_rows(1))
        edit_summary(self.regenerating, "config", "numCtx", 2048)
        result = self.compare("--qualification-trials", "1")
        self.assertEqual(2, result.returncode)
        self.assertIn("numCtx", json.loads(result.stdout)["error"])

    def test_server_version_is_reported_without_changing_comparison_scope(self):
        write_fixture(self.regenerating, 2, fixture_rows(2))
        edit_summary(self.regenerating, "sampling", "ollamaVersion", "synthetic-2")
        result = self.compare()
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual({"archived": "synthetic-1", "regenerated": "synthetic-2"},
                         report["ollamaVersions"])

    def test_impossible_null_evidence_is_rejected_even_when_both_inputs_match(self):
        for source, field, expected in (
            (0, "selfVerdict", "self-verification verdict"),
            (1, "selfRationale", "candidate selfRationale"),
            (1, "generation", "candidate generation"),
            (1, "code", "candidate code"),
        ):
            with self.subTest(field=field):
                rows = fixture_rows(2)
                rows[8][source][field] = None
                directory = self.workspace / field
                write_fixture(directory, 2, rows)
                result = self.compare(archived=directory, regenerated=directory)
                self.assertEqual(2, result.returncode)
                self.assertIn(expected, json.loads(result.stdout)["error"])

    def test_emitted_empty_replies_are_valid_records(self):
        rows = fixture_rows(2)
        trial, candidate = rows[8]
        trial.update(selfVerdict="fail", execOk=False)
        candidate.update(generation="", code="", selfRationale="", execOk=False)
        del candidate["selfReply"]
        write_fixture(self.regenerating, 2, rows)
        result = self.compare(archived=self.regenerating)
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        self.assertTrue(json.loads(result.stdout)["complete"])

    def test_invalid_step_or_required_evidence_refuses_the_comparison(self):
        for name, field, value, expected in (
            ("step", "step", 7, "candidate step"),
            ("missing-generation", "generation", None, "candidate generation"),
            ("execution", "execOk", False, "disagree on execOk"),
        ):
            with self.subTest(name=name):
                rows = fixture_rows(2)
                if name == "missing-generation":
                    del rows[0][1][field]
                else:
                    rows[0][1][field] = value
                directory = self.workspace / name
                write_fixture(directory, 2, rows)
                result = self.compare(regenerated=directory)
                self.assertEqual(result.returncode, 2)
                report = json.loads(result.stdout)
                self.assertEqual("INVALID", report["status"])
                self.assertIn(expected, report["error"])

    def test_report_never_overwrites_an_existing_file(self):
        write_fixture(self.regenerating, 2, fixture_rows(2))
        output = self.workspace / "comparison.json"
        first = self.compare("--out", str(output))
        self.assertEqual(first.returncode, 0, first.stderr or first.stdout)
        original = output.read_bytes()
        repeated = self.compare("--out", str(output))
        self.assertEqual(repeated.returncode, 2)
        self.assertEqual(original, output.read_bytes())
        self.assertEqual(hashlib.sha256(original).digest(), hashlib.sha256(first.stdout.encode()).digest())


if __name__ == "__main__":
    unittest.main()
