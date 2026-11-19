"""Exercise the hooked Node replay on fixed, benign, authored fixture programs."""

from argparse import Namespace
from collections import Counter
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import department_oracle_adapter as adapter
import department_oracle_capture as capture
from department_oracle_evidence import VARIANTS, decode_evidence
from oracle_audit import NODE_REPLAY
from prepare_department_regeneration import REPO, encoded, sha
import rescore_department_oracle as oracle
from summarize_department_regeneration import Skill


SCOPE = "SYNTHETIC_FIXTURE"
SESSION = sha(b"authored evaluator integration fixture")
DOUBLING = "function solve(n) { return n * 2; }"
LEXICAL = "const double = n => n * 2;\n'lexical fixture';"
ORDINARY_ERROR = "function solve(n) { if (n < 0) throw Error('fixture input'); return n; }"
FINITE_TIMEOUT = "function solve(n) { let sum = 0; for (let i = 0; i < n; i++) sum += i; return sum; }"
SETUP_ERROR = "function invalid( {"
LEXICAL_SKIP = "// process is a fixture comment for the historical skip\nfunction solve(n) { return n; }"
FIXTURES = {
    "second-family": [("double", DOUBLING), ("double", LEXICAL_SKIP)],
    "template-a": [("double", LEXICAL), ("identity", ORDINARY_ERROR)],
    "template-b": [("sum", FINITE_TIMEOUT), ("identity", SETUP_ERROR)],
}
TASKS = {
    "double": {"timeoutMs": 2000, "tests": [{"args": "[2]", "expected": "4"},
                                           {"args": "[9]", "expected": "0"},
                                           {"args": "[7]", "expected": "14"}]},
    "identity": {"timeoutMs": 2000, "tests": [{"args": '["dé"]', "expected": '"dé"'},
                                             {"args": "[-1]", "expected": "-1"}]},
    "sum": {"timeoutMs": 100, "tests": [{"args": "[8]", "expected": "28"},
                                         {"args": "[1000000000]", "expected": "499999999500000000"},
                                         {"args": "[6]", "expected": "15"}]},
}
DROPPED = {"double": ["[9]"]}


def utc_stamp():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class EngineFixture:
    """Invoke only the two existing replay entry shapes with the fixed fixtures above."""

    def __init__(self, root):
        self.root = root
        self.capture_dir = root / "capture"
        self.capture_dir.mkdir()
        self.node = Path(shutil.which("node")).resolve()
        artifact_path = self.capture_dir / "evaluator.bin"
        artifact_path.write_bytes(adapter.instrumented_engine())
        runtime_path = self.capture_dir / "node.bin"
        shutil.copyfile(self.node, runtime_path)
        phase = {"observationFinishedAt": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(
            timespec="microseconds")}
        self.phase_closed_at = phase["observationFinishedAt"]
        (root / "phase-result.json").write_bytes(encoded(phase))
        self.phase_pin = sha(encoded(phase))

        self.pairs = []
        groups = {}
        self.skill_groups = {}
        for group, definitions in FIXTURES.items():
            ordered = sorted(definitions, key=lambda item: (item[0], sha(item[1].encode())))
            self.pairs.extend(ordered)
            programs, skills = [], {}
            for task, code in ordered:
                digest = sha(code.encode())
                programs.append({"taskId": task, "codeSha256": digest, "historicalSkipApplies": code == LEXICAL_SKIP})
                verdict = "pass" if code != LEXICAL_SKIP else None
                skills[digest] = Skill(("sv1-ef1", 0, task, verdict, code), 1, 0, False)
            groups[group] = {"captureFilesSha256": {"trials.jsonl": sha(group.encode())}, "programs": programs}
            self.skill_groups[group] = skills, oracle.program_population(skills)
        contract = {"referenceReplayEngineSha256": adapter.REFERENCE_ENGINE_SHA256, "benchSha256": sha(encoded(TASKS)),
                    "tasks": {key: self.task_contract(key, task) for key, task in TASKS.items()}}
        manifest = {"groups": groups, "binding": {"phaseReceiptSha256": self.phase_pin,
                                                "ruleContractSha256": sha(encoded(contract))}}
        self.worklist = {"groups": list(FIXTURES)}
        self.document = {"scope": "REPLAY_MANIFEST_ONLY", "schema": oracle.REPORT_SCHEMA,
                         "manifest": manifest, "manifestSha256": sha(encoded(manifest)),
                         "ruleContract": contract, "ruleContractSha256": sha(encoded(contract)),
                         "worklistSha256": sha(encoded(self.worklist)),
                         "retainedOracleAuditSha256": oracle.MODEL_PINS["oracle-audit.json"],
                         "historicalBcaAbsoluteTolerance": oracle.HISTORICAL_BCA_ABSOLUTE_TOLERANCE,
                         "historicalClusteredPRelativeTolerance": oracle.HISTORICAL_CLUSTERED_P_RELATIVE_TOLERANCE,
                         "formalRunsStartedByReport": 0, "candidateExecutionsByReport": 0}
        self.manifest = root / "manifest.json"
        self.manifest.write_bytes(encoded(self.document))
        self.manifest_pin = sha(self.manifest.read_bytes())
        context = {"sessionId": SESSION, "evidenceScope": SCOPE, "manifestFileSha256": self.manifest_pin}
        data = json.dumps({"tasks": TASKS, "pairs": self.pairs, "dropped": DROPPED, "observationContext": context},
                          ensure_ascii=True, sort_keys=True).encode()
        self.input_pin = sha(data)
        (root / "authored-evaluator-input.json").write_bytes(data)
        invocation = {"schema": capture.INVOCATION_SCHEMA, "arguments": [], **context,
                      "referenceReplayEngineSha256": adapter.REFERENCE_ENGINE_SHA256,
                      "benchSha256": contract["benchSha256"], "evaluatorInputSha256": self.input_pin}
        (self.capture_dir / "invocation.json").write_bytes(encoded(invocation))
        self.snapshot("before")
        self.reference = self.run_node("-e", NODE_REPLAY, data=data)
        self.hooked = self.run_node(artifact_path, data=data)
        self.snapshot("after")
        (root / "process-exits.json").write_bytes(encoded({"legacy": self.reference.returncode,
                                                          "instrumented": self.hooked.returncode}))
        (root / "legacy-aggregate.json").write_bytes(self.reference.stdout)
        (root / "instrumented-aggregate.json").write_bytes(self.hooked.stdout)
        self.raw_events = self.capture_dir / capture.EVALUATOR_EVENTS_FILE
        self.raw_events.write_bytes(self.hooked.stderr)
        self.online_event_pin = sha(self.hooked.stderr)
        self.normalized = self.capture_dir / capture.EVENTS_FILE
        argv = [str(adapter.__file__), "bridge", "--replay-manifest", str(self.manifest),
                "--replay-manifest-sha256", self.manifest_pin, "--capture-directory", str(self.capture_dir),
                "--evaluator-events-sha256", self.online_event_pin]
        digest_stdout = StringIO()
        with patch.object(sys, "argv", argv), patch.object(sys, "stdout", digest_stdout):
            if adapter.main() != 0:
                raise AssertionError("fixture bridge command failed")
        if digest_stdout.getvalue().strip() != sha(self.normalized.read_bytes()):
            raise AssertionError("fixture bridge digest differs")
        self.review_file = root / "operator-review.json"
        self.review_raw = self.review()
        self.review_file.write_bytes(self.review_raw)

    @staticmethod
    def task_contract(key, task):
        return {"timeoutMs": task["timeoutMs"], "casesSha256": sha(encoded(task["tests"])),
                "caseIndices": list(range(len(task["tests"]))),
                "entryAndTestCaseIndices": [index for index, row in enumerate(task["tests"])
                                            if row["args"] not in DROPPED.get(key, ())]}

    def run_node(self, *arguments, data=None):
        return subprocess.run([str(self.node), *(str(arg) for arg in arguments)], input=data, cwd=REPO,
                              capture_output=True, check=True, timeout=30)

    def snapshot(self, side):
        version = self.run_node("--version")
        environment = self.run_node("-e", """
const {locale, timeZone} = new Intl.DateTimeFormat().resolvedOptions();
process.stdout.write(JSON.stringify({runtime: 'node', runtimeVersion: process.version, platform: process.platform,
  architecture: process.arch, osRelease: require('node:os').release(), locale, timeZone}));
""")
        data = json.loads(environment.stdout)
        data["schema"] = capture.ENVIRONMENT_SCHEMA
        (self.capture_dir / f"version-{side}.txt").write_bytes(version.stdout)
        (self.capture_dir / f"environment-{side}.json").write_bytes(encoded(data))

    def review(self, names=None):
        wanted = capture.CAPTURE_FILES | {capture.EVALUATOR_EVENTS_FILE} if names is None else names
        hashes, _ = capture.read_capture_files(self.capture_dir, wanted)
        return encoded({"schema": capture.REVIEW_SCHEMA, "evidenceScope": SCOPE,
                        "binding": self.document["manifest"]["binding"], "manifestFileSha256": self.manifest_pin,
                        "fileSha256": hashes, "attestation": {"operatorId": "synthetic-fixture-operator",
                                                             "reviewedAtUtc": utc_stamp(),
                                                             "decision": "ACCEPTED_CAPTURER_AND_EVIDENCE"}})

    def read_capture(self, review=None):
        return capture.read_capture(self.capture_dir, self.review_raw if review is None else review,
                                    self.document, self.manifest.read_bytes(), SCOPE, self.phase_closed_at)

    def run_pipeline(self):
        common = ["--regeneration-bundle", str(self.root), "--phase-receipt-sha256", self.phase_pin,
                  "--replay-manifest", str(self.manifest), "--replay-manifest-sha256", self.manifest_pin,
                  "--capture-directory", str(self.capture_dir), "--operator-review", str(self.review_file),
                  "--operator-review-sha256", sha(self.review_raw), "--evidence-mode", "synthetic"]

        def run(action, output, *additional):
            argv = [str(oracle.__file__), action, *common, *additional, "--out", str(output)]
            stream = BytesIO()
            phase = patch.multiple(oracle, prepare=lambda: self.worklist,
                                   rule_contract=lambda: self.document["ruleContract"],
                                   accepted_population=lambda *_: (self.document["manifest"], self.skill_groups),
                                   archive_readback=lambda *_: {})
            with phase, patch.object(sys, "argv", argv), patch.object(sys, "stdout", Namespace(buffer=stream)):
                if oracle.main() != 0:
                    raise AssertionError(f"fixture {action} command failed")
            if stream.getvalue() != output.read_bytes():
                raise AssertionError(f"fixture {action} output differs")
            return decode_evidence(stream.getvalue())

        packet = run("capture", self.root / "verified-capture.json")
        transcript_path = self.root / "replay-transcript.json"
        transcript = run("produce", transcript_path)
        score = run("score", self.root / "score-report.json", "--replay-transcript", str(transcript_path),
                    "--replay-transcript-sha256", sha(transcript_path.read_bytes()))
        return packet, transcript, score


class DepartmentOracleAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("node") is None:
            raise unittest.SkipTest("Node is required to test genuine evaluator events")
        runtime = REPO / ".runtime"
        runtime.mkdir(exist_ok=True)
        workspace = TemporaryDirectory(prefix="p2-r-evaluator-adapter-", dir=runtime)
        cls.addClassCleanup(workspace.cleanup)
        cls.fixture = EngineFixture(Path(workspace.name).resolve())

    def test_evaluator_emits_at_real_case_branches_with_equal_archive_output(self):
        fixture = self.fixture
        self.assertEqual(b"", fixture.reference.stderr)
        self.assertEqual(fixture.reference.stdout, fixture.hooked.stdout)
        rows = list(adapter.raw_rows(fixture.hooked.stderr))
        self.assertEqual({"REPLAY_START": 1, "REPLAY_FINISH": 1, "PROGRAM_SKIP": 1, "VARIANT_START": 15,
                          "VARIANT_FINISH": 15, "CASE_RESULT": 25}, Counter(row["event"] for row in rows))
        for row in (rows[0], rows[-1]):
            self.assertEqual(fixture.input_pin, row["evaluatorInputSha256"])
            self.assertEqual(SESSION, row["sessionId"])
            self.assertEqual(SCOPE, row["evidenceScope"])
            self.assertEqual(fixture.manifest_pin, row["manifestFileSha256"])
        failures = [row for row in rows if row.get("result") == "FAIL"]
        self.assertTrue(any(row["codeSha256"] == sha(ORDINARY_ERROR.encode()) for row in failures))
        timeouts = [row for row in rows if row.get("result") == "TIMEOUT"]
        self.assertEqual(list(VARIANTS), [row["variant"] for row in timeouts])
        self.assertEqual([1, 1, 1], [row["caseIndex"] for row in timeouts])
        self.assertTrue(all(row["elapsedNs"] > 0 for row in timeouts))
        self.assertIn("SETUP_ERROR", [row.get("status") for row in rows])
        self.assertIn("NO_CALLABLE", [row.get("status") for row in rows])

    def test_genuine_events_reach_capture_produce_and_score_without_a_formal_run(self):
        packet, transcript, score = self.fixture.run_pipeline()
        self.assertEqual(9, len(packet["provenance"]["fileSha256"]))
        self.assertEqual(self.fixture.online_event_pin, packet["provenance"]["evaluatorEventsFileSha256"])
        self.assertEqual(self.fixture.input_pin, packet["provenance"]["evaluatorInputSha256"])
        self.assertEqual(packet["provenance"], transcript["captureProvenance"])
        self.assertEqual(packet["provenance"], score["captureProvenance"])
        self.assertEqual("SYNTHETIC_REPLAY_TRANSCRIPT_SCORED", score["scope"])
        self.assertEqual(0, score["formalRunsStartedByReport"])
        self.assertEqual(0, score["candidateExecutionsByReport"])
        for group in ("second-family", "template-a"):
            labels = score["groups"][group]["labels"]
            self.assertEqual(1, labels["asRun"]["diagnostics"]["confusion"]["fp"]
                             - labels["entryAndTest"]["diagnostics"]["confusion"]["fp"])
        self.assertEqual(1, score["groups"]["template-b"]["outcomesByVariant"]["entry"]["TIMEOUT"])

    def test_bridge_rejects_changed_authentic_case_set_bench_or_candidate_and_truncation(self):
        fixture = self.fixture
        raw = fixture.raw_events.read_bytes()
        rows = list(adapter.raw_rows(raw))
        index = next(index for index, row in enumerate(rows) if row["event"] == "VARIANT_START" and row["taskId"] == "double")
        for changes, message in (
            ({"codeSha256": "0" * 64}, "different program, variant"),
            ({"casesSha256": "0" * 64}, "different program, variant"),
            ({"caseIndices": [0, 2]}, "different retained case set"),
            ({"timeoutMs": 1}, "different program, variant"),
        ):
            altered = [dict(row, **changes) if offset == index else row for offset, row in enumerate(rows)]
            payload = b"".join(json.dumps(row).encode() + b"\n" for row in altered)
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                self.reject_bridge(fixture, payload)
        with self.assertRaisesRegex(ValueError, "evaluator event: missing or unexpected evidence fields"):
            self.reject_bridge(fixture, b"\n".join(raw.splitlines()[:-1]) + b"\n")

    def reject_bridge(self, fixture, payload):
        original = fixture.raw_events.read_bytes()
        fixture.raw_events.write_bytes(payload)
        try:
            adapter.bridge_capture(fixture.capture_dir, fixture.document, fixture.manifest.read_bytes(), sha(payload))
        finally:
            fixture.raw_events.write_bytes(original)

    def test_instrumented_evidence_cannot_fall_back_to_manual_capture(self):
        fixture = self.fixture
        aside = fixture.root / "held-events.jsonl"
        fixture.raw_events.rename(aside)
        try:
            review = fixture.review(capture.CAPTURE_FILES)
            with self.assertRaisesRegex(ValueError, "must appear together"):
                fixture.read_capture(review)
        finally:
            aside.rename(fixture.raw_events)

    def test_repinning_normalized_cases_cannot_change_the_evaluator_observation(self):
        fixture = self.fixture
        original = fixture.normalized.read_bytes()
        rows = [decode_evidence(line) for line in original.splitlines()]
        row = next(row for row in rows if row.get("result") == "PASS")
        row["result"] = "FAIL"
        fixture.normalized.write_bytes(b"".join(json.dumps(row).encode() + b"\n" for row in rows))
        try:
            with self.assertRaisesRegex(ValueError, "normalized capture differs from the evaluator event stream"):
                fixture.read_capture(fixture.review())
        finally:
            fixture.normalized.write_bytes(original)

    def test_sidecar_refuses_relabelled_scope_session_or_independently_pinned_input(self):
        fixture = self.fixture
        path = fixture.capture_dir / "invocation.json"
        original = path.read_bytes()
        for changes in (
            {"evidenceScope": "OPERATOR_REVIEWED_EXTERNAL_REPLAY"},
            {"sessionId": "0" * 64},
            {"evaluatorInputSha256": "0" * 64},
        ):
            with self.subTest(changes=changes):
                path.write_bytes(encoded(dict(decode_evidence(original), **changes)))
                try:
                    with self.assertRaisesRegex(ValueError, "different program, variant, or boundary"):
                        adapter.bridge_capture(fixture.capture_dir, fixture.document, fixture.manifest.read_bytes(),
                                               fixture.online_event_pin)
                finally:
                    path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
