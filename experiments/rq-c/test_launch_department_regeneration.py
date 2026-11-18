"""Synthetic launch and retained-log controls. The department server is never contacted."""

from datetime import timedelta
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

import launch_department_regeneration as launch
from prepare_department_regeneration import DEPARTMENT_DRAFT_SHA, REPO, encoded, prepare, sha
from regen_compare_v2 import read_inputs
from test_prepare_department_regeneration import COMMIT, START, fixture_inputs


HOST = {"machine": "synthetic-host", "boot": "synthetic-boot", "os": "synthetic-os", "gpu": "synthetic-gpu",
        "driver": "synthetic-driver", "allocation": "synthetic-allocation"}
VERSION = "0.40.0"
APPROVAL_START = START + timedelta(minutes=1)
TEST_START = START + timedelta(minutes=2)
END = START + timedelta(hours=1)


def capture_raw(since, until, events=()):
    identity = {"schema": launch.LOG_CAPTURE, "host": HOST, "since": launch.stamp(since),
                "until": launch.stamp(until), "sources": {}}
    for label in launch.LOG_CLASSES:
        identity["sources"][label] = {"sourceId": f"synthetic-{label}", "querySha256": sha(label.encode()),
                                      "complete": True, "readableFrom": launch.stamp(since),
                                      "readableUntil": launch.stamp(until), "events": []}
    for label, event in events:
        identity["sources"][label]["events"].append(event)
    return identity


class FixtureRuntime:
    def __init__(self, worklist, inputs, failure=None):
        self.next_time = TEST_START
        self.commands = []
        self.failure = failure
        self.inputs = inputs
        self.worklist = worklist
        self.gap_error_at = None

    def clock(self):
        self.next_time += timedelta(seconds=1)
        return self.next_time

    def capture(self, bundle, label, since, until):
        historical_at = START + timedelta(seconds=1)
        events = []
        if since <= historical_at < until:
            events.append(("system", {"id": "historical", "at": launch.stamp(historical_at),
                                      "record": "synthetic event"}))
        if self.gap_error_at and since <= self.gap_error_at < until:
            events.append(("gpu", {"id": "gap-error", "at": launch.stamp(self.gap_error_at),
                                   "record": "synthetic error after qualification"}))
        if label == "after" and self.failure == "new-event":
            events.append(("gpu", {"id": "blocked", "at": launch.stamp(until - timedelta(seconds=1)),
                                   "record": "synthetic new GPU error"}))
        value = capture_raw(since, until, events)
        if label == "before" and self.failure == "no-access":
            value["sources"]["gpu"]["complete"] = False
        path = bundle / f"logs-{label}.json"
        launch.write(path, value)
        return path.read_bytes()

    def unloaded(self, model, digest, evidence):
        launch.write(evidence, {"model": model, "digest": digest, "version": VERSION, "before": [],
                                "after": [] if self.failure != "resident" else [{"name": model, "digest": digest}],
                                "unloadResponse": None})
        return VERSION

    def run(self, argv, log):
        self.commands.append(argv)
        log.write_text("[warm-up] model loaded; first-request output discarded\n")
        if self.failure == "runner-failed":
            return 7
        model = argv[argv.index("--model") + 1]
        out = Path(argv[argv.index("--out") + 1])
        if "verify" in argv:
            control = next(row for row in self.worklist["positiveControls"] if row["model"] == model)
            launch.write(out, {"model": model, "digest": control["modelDigest"], "serverVersion": VERSION,
                               "verdict": "pass", "discriminative": True, "check": {"seedStrategy": "fixed", "runs": 5},
                               "control": {"verdict": "divergent", "runs": 5, "uniqueOutputs": 5,
                                           "perRun": [{"index": i, "hash": f"synthetic-{i}"} for i in range(5)],
                                           "sampling": control["openedSampling"]}})
            return 0
        template = argv[argv.index("--verify-template") + 1]
        group = next(row for row in self.worklist["groups"] if (row["model"], row["verifierTemplate"]) == (model, template))
        trials = argv[argv.index("--trials") + 1]
        if trials == "5":
            files = self.inputs[group["id"]]
        else:
            files = read_inputs(REPO / group["historicalRun"]["directory"])
            summary = json.loads(files["summary.json"])
            summary["gitHash"] = COMMIT
            files["summary.json"] = encoded(summary)
        path = out / f"rq-c-s42-ollama-t{trials}-r5"
        path.mkdir()
        for name, raw in files.items():
            (path / name).write_bytes(raw)
        return 0


class DepartmentLaunchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worklist = prepare()
        cls.inputs = {group["id"]: fixture_inputs(group) for group in cls.worklist["groups"]}

    def setUp(self):
        runtime = REPO / ".runtime"
        runtime.mkdir(exist_ok=True)
        directory = TemporaryDirectory(prefix="p2-r-launch-controls-", dir=runtime)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        build = self.root / "build"
        build.mkdir()
        for name in ("rqc.dll", "substrate.dll", "dependency.dat"):
            (build / name).write_text(f"synthetic fixture {name}; never executable")
        for name in ("dotnet", "collector"):
            path = self.root / name
            path.write_text("#!/bin/sh\nexit 99\n")
            path.chmod(0o700)
        (self.root / "reply.eml").write_text("Synthetic test control; no actual supervisor reply.")
        (self.root / "approved-plan.pdf").write_text("Synthetic test control; no actual approved plan.")
        self.approval = {
            "schema": launch.APPROVAL, "scope": "P2-R-department", "phases": list(launch.PHASES),
            "reviewedDraftSha256": DEPARTMENT_DRAFT_SHA, "worklistSha256": sha(encoded(self.worklist)),
            "supervisorReply": {"path": "reply.eml", "sha256": sha((self.root / "reply.eml").read_bytes()),
                                "reviewedSender": "synthetic-reviewed-supervisor",
                                "receivedAt": launch.stamp(START)},
            "approvedPlan": {"path": "approved-plan.pdf", "sha256": sha((self.root / "approved-plan.pdf").read_bytes())},
            "sourceCommit": COMMIT, "logHistorySince": launch.stamp(START),
            "notBefore": launch.stamp(APPROVAL_START), "notAfter": launch.stamp(END),
            "host": HOST, "ollamaUrl": "http://synthetic.invalid:11434", "ollamaVersion": VERSION,
            "build": {"directory": "build", "rqcDll": "rqc.dll", "substrateDll": "substrate.dll",
                      "files": launch.manifest_files(build)},
            "dotnet": {"path": str(self.root / "dotnet"), "sha256": sha((self.root / "dotnet").read_bytes())},
            "logCollector": {"path": str(self.root / "collector"), "sha256": sha((self.root / "collector").read_bytes())},
        }
        self.approval_path = self.root / "approval.json"
        self.pin = self.save()
        _, self.tools = self.check()

    def save(self):
        raw = encoded(self.approval)
        self.approval_path.write_bytes(raw)
        return sha(raw)

    def check(self, pin=None, phase="qualification", current=TEST_START):
        return launch.approved(self.approval_path, self.pin if pin is None else pin, phase, self.worklist,
                               COMMIT, lambda: current)

    def perform(self, name, phase="qualification", failure=None, proof=None, gap=False):
        bundle = self.root / name
        runtime = FixtureRuntime(self.worklist, self.inputs, failure)
        if proof:
            boundary = launch.instant(proof["finalLogs"]["until"])
            runtime.next_time = boundary + timedelta(minutes=5)
            if gap:
                runtime.gap_error_at = boundary + timedelta(minutes=1)
        report = launch.perform(phase, bundle, self.approval, self.pin, self.tools, self.worklist, runtime, proof)
        return bundle, report, runtime.commands

    def cli(self, *args):
        return subprocess.run([sys.executable, "-B", str(Path(launch.__file__)), *map(str, args)],
                              cwd=REPO, capture_output=True)

    def test_cli_offline_plan_only(self):
        result = self.cli("plan")
        self.assertEqual(0, result.returncode, result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual("OFFLINE_COMMAND_PLAN", record["status"])
        self.assertEqual(0, record["formalRunsStarted"])
        self.assertEqual([5, 5, 5], [len(group["qualification"]) for group in record["groups"]])
        self.assertEqual("NOT_RUN", record["regeneration"])
        self.assertEqual(2, len(record["positiveControls"]))

    def test_changes_to_reply_and_build_are_rejected(self):
        self.assertRaisesRegex(ValueError, "approval receipt SHA", self.check, "1" * 64)
        reply = self.root / "reply.eml"
        before = reply.read_bytes()
        reply.write_bytes(before + b"tampered")
        self.assertRaisesRegex(ValueError, "file identity differs", self.check)
        reply.write_bytes(before)
        (self.root / "build/dependency.dat").write_text("tampered dependent binary")
        self.assertRaisesRegex(ValueError, "frozen build files differ", self.check)

    def test_approval_pins_relative_collector_configuration(self):
        settings = self.root / "collector.json"
        settings.write_bytes(b"synthetic config bytes")
        self.approval["logCollector"]["config"] = {"path": settings.name, "sha256": sha(settings.read_bytes())}
        self.pin = self.save()
        self.assertEqual(settings, self.check()[1]["logCollectorConfig"])
        settings.write_bytes(b"other bytes")
        self.assertRaisesRegex(ValueError, "file identity differs", self.check)

    def test_scope_future_reply_and_expiry_gate(self):
        self.assertRaisesRegex(ValueError, "time window", self.check, current=END)
        self.approval["phases"] = ["qualification"]
        self.pin = self.save()
        self.assertRaisesRegex(ValueError, "does not allow", self.check, phase="regeneration")
        self.approval["supervisorReply"]["receivedAt"] = launch.stamp(END)
        self.pin = self.save()
        self.assertRaisesRegex(ValueError, "time window", self.check)

    def test_separate_approved_windows_reuse_same_qualified_identity(self):
        future = END + timedelta(minutes=2)
        prior, _ = launch.approved(self.approval_path, self.pin, "qualification", self.worklist,
                                   COMMIT, lambda: future, historical=True)
        next_path = self.root / "approved-regeneration.json"
        current = deepcopy(self.approval)
        current["phases"] = ["regeneration"]
        current["notBefore"] = launch.stamp(END + timedelta(minutes=1))
        current["notAfter"] = launch.stamp(END + timedelta(hours=1))
        current["logHistorySince"] = launch.stamp(END)
        current["host"]["allocation"] = "another-time-slot-for-the-same-synthetic-gpu"
        current["supervisorReply"]["receivedAt"] = launch.stamp(END + timedelta(seconds=1))
        next_path.write_bytes(encoded(current))
        recent, _ = launch.approved(next_path, sha(next_path.read_bytes()), "regeneration", self.worklist,
                                    COMMIT, lambda: future)
        launch.same_qualification_identity(prior, recent)
        relocated = deepcopy(recent)
        relocated["logCollector"]["path"] = "/another/path/to/the/same/collector"
        launch.same_qualification_identity(prior, relocated)
        relocated["logCollector"]["sha256"] = "1" * 64
        self.assertRaisesRegex(ValueError, "differs from qualification", launch.same_qualification_identity, prior, relocated)
        for field, changed in (("boot", "different-boot"), ("gpu", "different-device")):
            wrong = deepcopy(recent)
            wrong["host"][field] = changed
            with self.subTest(field=field):
                self.assertRaisesRegex(ValueError, "differs from qualification", launch.same_qualification_identity,
                                       prior, wrong)
        recent["supervisorReply"]["reviewedSender"] = "different-sender"
        self.assertRaisesRegex(ValueError, "differs from qualification", launch.same_qualification_identity, prior, recent)

    def test_cli_logs_reject_unreadable_mismatched_and_shifted_sources(self):
        before = capture_raw(START, TEST_START)
        after = capture_raw(START, END)
        left, right = self.root / "before.json", self.root / "after.json"
        left.write_bytes(encoded(before))
        right.write_bytes(encoded(after))
        result = self.cli("audit-logs", "--before", left, "--after", right)
        self.assertEqual("NO_NEW_RELEVANT_EVENTS_IN_CAPTURE", json.loads(result.stdout)["status"])
        for key, val, message in (
            ("sourceId", "substituted", "pre/post log source"),
            ("querySha256", "b" * 64, "pre/post log source"),
            ("readableUntil", launch.stamp(TEST_START), "did not cover"),
            ("complete", False, "did not cover"),
        ):
            with self.subTest(key=key):
                changed = capture_raw(START, END)
                changed["sources"]["gpu"][key] = val
                right.write_bytes(encoded(changed))
                result = self.cli("audit-logs", "--before", left, "--after", right)
                self.assertEqual(2, result.returncode)
                self.assertIn(message, result.stderr.decode())

    def test_late_baseline_records_cannot_be_counted_as_newly_generated_errors(self):
        before = encoded(capture_raw(START, TEST_START))
        historical = {"id": "late", "at": launch.stamp(APPROVAL_START), "record": "synthetic late event"}
        after = encoded(capture_raw(START, END, [("system", historical)]))
        self.assertRaisesRegex(ValueError, "baseline changed", launch.audit_logs, before, after,
                               START, TEST_START, END, HOST)

    def test_full_synthetic_qualification_and_regeneration(self):
        bundle, report, commands = self.perform("qualification")
        self.assertEqual("QUALIFICATION_EVIDENCE_COMPLETE", report["status"], report)
        self.assertEqual((15, 17), (report["launchesStarted"], len(commands)))
        self.assertTrue(all("--resume-from" not in x and "--overwrite" not in x for x in commands))
        self.assertEqual(17, len({x[x.index("--out") + 1] for x in commands}))
        qualification_sha = sha((bundle / "phase-result.json").read_bytes())
        proof = launch.proven_qualification(bundle, qualification_sha, self.pin, self.approval, self.worklist)
        self.assertEqual(qualification_sha, proof["sha256"])
        _, regenerated, commands = self.perform("regeneration", phase="regeneration", proof=proof)
        self.assertEqual("REGENERATION_EVIDENCE_COMPLETE", regenerated["status"], regenerated)
        self.assertEqual(3, len(commands))
        self.assertEqual(qualification_sha, regenerated["qualificationReceiptSha256"])
        self.assertRaisesRegex(ValueError, "file identity differs", launch.proven_qualification,
                               bundle, "9" * 64, self.pin, self.approval, self.worklist)
        raw = bundle / "qualification/controls/control-1.json"
        raw.write_bytes(raw.read_bytes() + b" ")
        self.assertRaisesRegex(ValueError, "bound files", launch.proven_qualification,
                               bundle, qualification_sha, self.pin, self.approval, self.worklist)

    def test_regeneration_refuses_missing_gap_coverage_and_gap_events(self):
        qualified = capture_raw(START, APPROVAL_START)
        baseline = capture_raw(APPROVAL_START - timedelta(seconds=10), TEST_START)
        proof = {"sha256": "e" * 64, "finalLogs": qualified}
        self.assertEqual("QUALIFICATION_HANDOFF_LOGS_COVERED", launch.audit_handoff(qualified, baseline)["status"])
        late = capture_raw(APPROVAL_START + timedelta(seconds=1), TEST_START)
        self.assertRaisesRegex(ValueError, "does not cover", launch.audit_handoff, qualified, late)
        baseline["sources"]["system"]["querySha256"] = "6" * 64
        self.assertRaisesRegex(ValueError, "differs from qualification", launch.audit_handoff, qualified, baseline)
        # Both complete exports can agree on a new event while the handoff remains blocked.
        original = capture_raw(START, APPROVAL_START, [
            ("system", {"id": "historical", "at": launch.stamp(START + timedelta(seconds=1)),
                        "record": "synthetic event"}),
        ])
        proof["finalLogs"] = original
        _, report, commands = self.perform("gap-event", phase="regeneration", proof=proof, gap=True)
        self.assertEqual((0, []), (report["launchesStarted"], commands))
        self.assertIn("event between qualification and regeneration", report["error"])

    def test_pre_capture_and_unload_refuse_before_subprocess(self):
        for failure in ("no-access", "resident"):
            with self.subTest(failure=failure):
                bundle, report, commands = self.perform(failure, failure=failure)
                self.assertEqual("INCOMPLETE_DEPARTMENT_EVIDENCE", report["status"], report)
                self.assertEqual((0, []), (report["launchesStarted"], commands))
                self.assertTrue((bundle / "logs-before.json").is_file())
                self.assertTrue((bundle / "logs-after.json").is_file())

    def test_affected_or_interrupted_results_stay_in_failed_bundles(self):
        bundle, report, commands = self.perform("new-event", failure="new-event")
        self.assertEqual("DEPARTMENT_PHASE_REQUIRES_INVESTIGATION", report["status"])
        self.assertEqual(["blocked"], report["logs"]["eventIdsBySource"]["gpu"])
        self.assertEqual(17, len(commands))
        pin = sha((bundle / "phase-result.json").read_bytes())
        self.assertRaisesRegex(ValueError, "qualification receipt", launch.proven_qualification,
                               bundle, pin, self.pin, self.approval, self.worklist)
        _, partial, commands = self.perform("runner-failed", failure="runner-failed")
        self.assertEqual("INCOMPLETE_DEPARTMENT_EVIDENCE", partial["status"], partial)
        self.assertEqual((1, 1), (partial["launchesStarted"], len(commands)))
        self.assertIn("runner exited 7", partial["error"])


if __name__ == "__main__":
    unittest.main()
