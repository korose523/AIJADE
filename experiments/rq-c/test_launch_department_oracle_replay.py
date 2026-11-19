"""Exercise formal replay evidence with a tiny, authored synthetic regeneration."""

from argparse import Namespace
from datetime import timedelta
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import socket
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import department_oracle_capture as capture
from department_oracle_process import (
    APPROVAL_SCHEMA, COMPLETE, INPUT_FILE, PROCESS_FILE, PROCESS_FILES, RAW_EVENTS_FILE, STDOUT_FILE,
    STREAM_FILES, streams,
)
import launch_department_oracle_replay as replay
import launch_department_regeneration as launch
from prepare_department_regeneration import REPO, encoded, sha
from regen_compare_v2 import CONDITIONS
import rescore_department_oracle as oracle
from test_department_oracle_adapter import (
    DOUBLING, DROPPED, EngineFixture, FINITE_TIMEOUT, LEXICAL, SCOPE, TASKS, utc_stamp,
)
from test_launch_department_regeneration import END, HOST, VERSION, FixtureRuntime, capture_raw
from test_prepare_department_regeneration import COMMIT, START


AUTHORED = {"second-family": ("double", DOUBLING), "template-a": ("double", LEXICAL),
            "template-b": ("sum", FINITE_TIMEOUT)}
SESSION = sha(b"offline authored regeneration to replay")


def lines(records):
    return b"".join(json.dumps(row, sort_keys=True).encode() + b"\n" for row in records)


def fixture_inputs(group, model):
    trials, candidates = [], []
    task, code = AUTHORED[group]
    for index, cell in enumerate(CONDITIONS):
        skill = f"{group}:{cell}"
        verdict = "pass" if cell.startswith("sv1") else None
        trials.append({"condition": cell, "trial": 0, "round": 0, "taskId": task, "skillId": skill, "reused": False,
                       "execOk": False, "selfVerdict": verdict})
        candidates.append({"step": index, "skillId": skill, "reused": False, "execOk": False, "code": code,
                           "generation": "authored benign fixture", "selfRationale": "fixture" if verdict else None})
    config = {"trials": 1, "rounds": 1, "tasks": 1, "pruneMinCalls": 1, "maxReplyTokens": 32, "numCtx": 512,
              "seed": 42, "pCorrect": 0.9, "pruneThreshold": 0.7, "backend": "ollama", "model": model,
              "domain": "executable", "verifyTemplate": "B" if group == "template-b" else "A"}
    sampling = {"mode": "live", "model": model, "temperature": 0, "seed": 3759066737,
                "modelDigest": sha(model.encode()), "ollamaVersion": VERSION, "warmUp": True}
    summary = {"config": config, "conditions": list(CONDITIONS), "sampling": sampling, "gitHash": COMMIT,
               "nExecutions": len(trials), "nSkills": len(trials)}
    return {"trials.jsonl": lines(trials), "candidates.jsonl": lines(candidates), "summary.json": encoded(summary)}


class SyntheticRegenerator(FixtureRuntime):
    def run(self, argv, log):
        model = argv[argv.index("--model") + 1]
        directory = Path(argv[argv.index("--out") + 1]) / "authored-run"
        directory.mkdir()
        for name, raw in self.inputs[model].items():
            (directory / name).write_bytes(raw)
        log.write_bytes(b"authored fixture only\n")
        return 0


class ReplayFixture:
    def __init__(self, root):
        self.root = root
        self.regeneration = root / "synthetic-regeneration"
        self.process = root / "synthetic-replay"
        self.contract = {"referenceReplayEngineSha256": replay.sha(oracle.NODE_REPLAY.encode()),
                         "benchSha256": sha(encoded(TASKS)), "removedCaseArgs": DROPPED,
                         "tasks": {name: EngineFixture.task_contract(name, task) for name, task in TASKS.items()}}
        work, inputs = [], {}
        for group in AUTHORED:
            model = "fixture-" + group
            data = inputs[model] = fixture_inputs(group, model)
            archived = root / "authored-reference" / group
            archived.mkdir(parents=True)
            for name, raw in data.items():
                (archived / name).write_bytes(raw)
            summary = json.loads(data["summary.json"])
            subdir = "regeneration/" + group
            work.append({"id": group, "model": model,
                         "historicalRun": {"directory": os.path.relpath(archived, REPO),
                                           "fileSha256": {name: sha(raw) for name, raw in data.items()},
                                           "config": summary["config"], "modelDigest": summary["sampling"]["modelDigest"]},
                         "regeneration": {"directory": subdir, "artifacts": subdir + "/authored-run",
                                          "argvTemplate": ["{dotnet}", "{frozenRqcDll}", "--model", model,
                                                           "--out", "{bundleRoot}/" + subdir],
                                          "steps": summary["nExecutions"]}})
        self.worklist = {"schema": "authored fixture worklist", "groups": work}
        stub = SyntheticRegenerator(self.worklist, inputs)
        regen_approval = {"sourceCommit": COMMIT, "ollamaVersion": VERSION, "host": HOST,
                          "ollamaUrl": "http://fixture.invalid:11434",
                          "logHistorySince": launch.stamp(START), "notAfter": launch.stamp(END),
                          "build": {"rqcDll": "inert.dll", "files": {"inert.dll": "3" * 64}}}
        qualification = {"sha256": "4" * 64,
                         "finalLogs": capture_raw(START, START + timedelta(seconds=2),
                                                  [("system", {"id": "historical",
                                                               "at": launch.stamp(START + timedelta(seconds=1)),
                                                               "record": "synthetic event"})])}
        phase = launch.perform("regeneration", self.regeneration, regen_approval, "5" * 64,
                               {"dotnet": root / "inert-dotnet", "rqcDll": root / "inert.dll",
                                "substrateDll": root / "inert-substrate.dll"},
                               self.worklist, stub, qualification)
        if phase["status"] != "REGENERATION_EVIDENCE_COMPLETE" or phase["launchesStarted"] != 3:
            raise AssertionError(phase)
        self.phase_pin = launch.digest_file(self.regeneration / "phase-result.json")
        admitted, _ = oracle.accepted_population(self.regeneration, self.phase_pin, self.worklist, self.contract)
        self.manifest = root / "manifest.json"
        self.manifest.write_bytes(encoded(dict(oracle.report_header(self.worklist, self.contract),
                                               scope="REPLAY_MANIFEST_ONLY", manifest=admitted,
                                               manifestSha256=sha(encoded(admitted)))))
        self.manifest_pin = sha(self.manifest.read_bytes())
        self.document, groups, self.closed, self.regeneration_approval_pin = replay.accepted_inputs(
            self.regeneration, self.phase_pin, self.manifest.read_bytes(), self.worklist, self.contract)
        self.payload, self.invocation = replay.build_input(self.document, groups, TASKS, SCOPE, SESSION)
        node = self.node = Path(shutil.which("node")).resolve()
        now = launch.now()
        deadline = now + timedelta(minutes=4)
        _, environment = replay.runtime_snapshot(node, root, deadline)
        approval = {"schema": APPROVAL_SCHEMA, "scope": "P2-R-department-oracle-replay",
                    **replay.process_binding({"sourceCommit": COMMIT,
                                              "regenerationApprovalSha256": self.regeneration_approval_pin},
                                             self.invocation, admitted),
                    "evaluatorSha256": sha(replay.instrumented_engine()),
                    "node": {"path": str(node), "sha256": launch.digest_file(node), "environment": environment},
                    "hostName": socket.gethostname(), "notBefore": launch.stamp(now - timedelta(minutes=1)),
                    "notAfter": launch.stamp(deadline),
                    "supervisorReply": {"path": "synthetic", "sha256": "6" * 64, "reviewedSender": "offline fixture",
                                        "receivedAt": launch.stamp(now - timedelta(minutes=2))},
                    "approvedPlan": {"path": "synthetic", "sha256": "7" * 64}}
        self.approval = encoded(approval)
        self.receipt = replay.staged_replay(self.process, self.document, self.payload, self.invocation,
                                            self.approval, node, self.closed)
        if self.receipt["status"] != COMPLETE:
            raise AssertionError(self.receipt)
        self.review = root / "operator-review.json"
        self.review.write_bytes(self.review_bytes())

    def review_bytes(self):
        names = capture.CAPTURE_FILES | PROCESS_FILES | {RAW_EVENTS_FILE}
        hashes, _ = capture.read_capture_files(self.process, names)
        return encoded({"schema": capture.REVIEW_SCHEMA, "evidenceScope": SCOPE,
                        "binding": self.document["manifest"]["binding"], "manifestFileSha256": self.manifest_pin,
                        "fileSha256": hashes, "attestation": {"operatorId": "synthetic-offline-reviewer",
                                                             "reviewedAtUtc": utc_stamp(),
                                                             "decision": "ACCEPTED_CAPTURER_AND_EVIDENCE"}})

    def verify(self, review=None):
        return capture.read_capture(self.process, self.review.read_bytes() if review is None else review,
                                    self.document, self.manifest.read_bytes(), SCOPE, self.closed,
                                    self.regeneration_approval_pin)

    def pipeline(self):
        common = ["--regeneration-bundle", str(self.regeneration), "--phase-receipt-sha256", self.phase_pin,
                  "--replay-manifest", str(self.manifest), "--replay-manifest-sha256", self.manifest_pin,
                  "--capture-directory", str(self.process), "--operator-review", str(self.review),
                  "--operator-review-sha256", sha(self.review.read_bytes()), "--evidence-mode", "synthetic"]

        def run(action, filename, *additional):
            output = self.root / filename
            argv = [str(oracle.__file__), action, *common, *additional, "--out", str(output)]
            stdout = BytesIO()
            checks = patch.multiple(oracle, prepare=lambda: self.worklist, rule_contract=lambda: self.contract,
                                    archive_readback=lambda *_: {})
            with checks, patch.object(sys, "argv", argv), patch.object(sys, "stdout", Namespace(buffer=stdout)):
                if oracle.main() != 0:
                    raise AssertionError(f"fixture {action} command failed")
            if stdout.getvalue() != output.read_bytes():
                raise AssertionError(f"fixture {action} file differs")
            return json.loads(stdout.getvalue())

        packet = run("capture", "verified-capture.json")
        transcript = run("produce", "transcript.json")
        transcript_path = self.root / "transcript.json"
        score = run("score", "score.json", "--replay-transcript", str(transcript_path),
                    "--replay-transcript-sha256", launch.digest_file(transcript_path))
        return packet, transcript, score


class DepartmentOracleReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("node") is None:
            raise unittest.SkipTest("Node is required to exercise retained real process outcomes")
        directory = REPO / ".runtime"
        directory.mkdir(exist_ok=True)
        temporary = TemporaryDirectory(prefix="p2-r-replay-process-controls-", dir=directory)
        cls.addClassCleanup(temporary.cleanup)
        cls.fixture = ReplayFixture(Path(temporary.name).resolve())

    def test_full_regeneration_admission_to_real_authored_replay_and_score(self):
        packet, transcript, score = self.fixture.pipeline()
        proof = packet["provenance"]
        self.assertEqual(proof, transcript["captureProvenance"])
        self.assertEqual(proof, score["captureProvenance"])
        self.assertEqual({"programs": 3, "variants": 9}, proof["stdoutReadback"])
        self.assertEqual(13, len(proof["fileSha256"]))
        self.assertEqual(0, proof["processExitCode"])
        self.assertGreater(proof["stdoutBytes"], 0)
        self.assertGreater(proof["rawStderrBytes"], 0)
        self.assertEqual("SYNTHETIC_REPLAY_TRANSCRIPT_SCORED", score["scope"])
        for name in ("second-family", "template-a"):
            self.assertEqual(2, score["groups"][name]["labels"]["entryAndTest"]["diagnostics"]["confusion"]["tp"])
        self.assertEqual(1, score["groups"]["template-b"]["outcomesByVariant"]["entry"]["TIMEOUT"])

    def test_readback_refuses_a_rebound_nonzero_exit(self):
        fixture = self.fixture
        path = fixture.process / PROCESS_FILE
        original = path.read_bytes()
        path.write_bytes(encoded(dict(json.loads(original), exitCode=7)))
        try:
            with self.assertRaisesRegex(ValueError, "process did not exit successfully"):
                fixture.verify(fixture.review_bytes())
        finally:
            path.write_bytes(original)

    def test_process_window_must_cover_both_output_boundaries(self):
        fixture = self.fixture
        path = fixture.process / PROCESS_FILE
        original = path.read_bytes()
        path.write_bytes(encoded(dict(json.loads(original), finishedAtUtc=fixture.closed)))
        try:
            with self.assertRaisesRegex(ValueError, "process timestamps"):
                fixture.verify(fixture.review_bytes())
        finally:
            path.write_bytes(original)

    def test_stdout_rebound_truncation_or_case_disagreement_is_refused(self):
        fixture = self.fixture
        report_path, stdout_path = (fixture.process / name for name in (PROCESS_FILE, STDOUT_FILE))
        receipt, stdout = report_path.read_bytes(), stdout_path.read_bytes()
        for tamper, expected in (
            (lambda rows: rows[:-1], "full program population"),
            (lambda rows: [dict(rows[0], asRun=dict(rows[0]["asRun"], ok=True)), *rows[1:]], "stdout verdict"),
            (lambda rows: [dict(rows[0], asRun=dict(rows[0]["asRun"], failing=[
                dict(rows[0]["asRun"]["failing"][0], expected="wrong authored expected"),
            ])), *rows[1:]], "stdout failure does not bind"),
        ):
            with self.subTest(guard=expected):
                stdout_path.write_bytes(encoded(tamper(json.loads(stdout))))
                report_path.write_bytes(encoded(dict(json.loads(receipt), fileEvidence=streams(
                    {name: (fixture.process / name).read_bytes() for name in STREAM_FILES}))))
                try:
                    with self.assertRaisesRegex(ValueError, expected):
                        fixture.verify(fixture.review_bytes())
                finally:
                    report_path.write_bytes(receipt)
                    stdout_path.write_bytes(stdout)

    def test_real_nonzero_probe_preserves_both_unmodified_streams(self):
        target = self.fixture.root / "nonzero-process-probe"
        target.mkdir()
        (target / "evaluator.bin").write_bytes(
            b"process.stdout.write('fixture stdout\\n'); process.stderr.write('fixture stderr\\n'); process.exitCode = 7;\n")
        (target / INPUT_FILE).write_bytes(b"")
        result = replay.run_process(self.fixture.node, target, launch.now() + timedelta(seconds=15))
        (target / PROCESS_FILE).write_bytes(encoded(result))
        self.assertIs(True, result["processStarted"])
        self.assertEqual("EXITED", result["termination"])
        self.assertEqual(7, result["exitCode"])
        self.assertEqual(b"fixture stdout\n", (target / STDOUT_FILE).read_bytes())
        self.assertEqual(b"fixture stderr\n", (target / RAW_EVENTS_FILE).read_bytes())

    def test_real_timeout_retains_partial_streams_and_observed_exit(self):
        target = self.fixture.root / "timeout-process-probe"
        target.mkdir()
        (target / "evaluator.bin").write_bytes(
            b"process.stdout.write('partial stdout\\n'); process.stderr.write('partial stderr\\n'); "
            b"setTimeout(() => {}, 30000);\n")
        (target / INPUT_FILE).write_bytes(b"")
        result = replay.run_process(self.fixture.node, target, launch.now() + timedelta(seconds=2))
        (target / PROCESS_FILE).write_bytes(encoded(result))
        self.assertIs(True, result["processStarted"])
        self.assertEqual("TIMEOUT", result["termination"])
        self.assertIs(type(result["exitCode"]), int)
        self.assertNotEqual(0, result["exitCode"])
        self.assertEqual(b"partial stdout\n", (target / STDOUT_FILE).read_bytes())
        self.assertEqual(b"partial stderr\n", (target / RAW_EVENTS_FILE).read_bytes())

    def test_interrupt_reaps_without_removing_the_raw_stream_prefix(self):
        target = self.fixture.root / "interrupted-process-probe"
        target.mkdir()
        (target / INPUT_FILE).write_bytes(b"")

        class InterruptedProbe:
            def __init__(self, *_, stdout, stderr, **kwargs):
                stdout.write(b"interrupted stdout\n")
                stderr.write(b"interrupted stderr\n")
                self.returncode = None
                self.killed = False

            def wait(self, timeout):
                if not self.killed:
                    raise KeyboardInterrupt
                if timeout <= 0 or timeout > 5:
                    raise AssertionError("cleanup wait must be bounded")
                self.returncode = -9

            def kill(self):
                self.killed = True

        with patch.object(replay.subprocess, "Popen", InterruptedProbe):
            result = replay.run_process(self.fixture.node, target, launch.now() + timedelta(seconds=15))
        (target / PROCESS_FILE).write_bytes(encoded(result))
        self.assertEqual("INTERRUPTED", result["termination"])
        self.assertEqual(-9, result["exitCode"])
        self.assertEqual(b"interrupted stdout\n", (target / STDOUT_FILE).read_bytes())
        self.assertEqual(b"interrupted stderr\n", (target / RAW_EVENTS_FILE).read_bytes())

    def test_production_input_gate_checks_actual_host_and_original_approved_plan(self):
        fixture = self.fixture
        approval = dict(json.loads(fixture.approval), evidenceScope=replay.EXTERNAL)
        invocation = dict(fixture.invocation, evidenceScope=replay.EXTERNAL)
        manifest = fixture.document["manifest"]
        original = {"schema": replay.REGENERATION_APPROVAL, "scope": "P2-R-department", "phases": ["regeneration"],
                    "sourceCommit": manifest["binding"]["sourceCommit"],
                    "worklistSha256": manifest["binding"]["worklistSha256"],
                    "supervisorReply": approval["supervisorReply"], "approvedPlan": {"sha256": "0" * 64}}
        arguments = [fixture.root / "fixture-approval.json", approval, original, fixture.regeneration_approval_pin,
                     invocation, manifest, approval["evaluatorSha256"], fixture.closed, approval["sourceCommit"]]
        with self.assertRaisesRegex(ValueError, "does not carry forward the accepted P2-R plan"):
            replay.reviewed_approval(*arguments)
        approval["hostName"] = "different-assigned-fixture-host"
        with self.assertRaisesRegex(ValueError, "different scope, checkout or host"):
            replay.reviewed_approval(*arguments)


if __name__ == "__main__":
    unittest.main()
