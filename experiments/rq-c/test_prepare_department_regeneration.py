"""Offline controls for the P2-R execution worklist and captured-repeat reader."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from prepare_department_regeneration import REPO, audit, encoded, prepare, sha
from regen_compare_v2 import CONDITIONS, INPUT_NAMES, load_rows, read_inputs


COMMIT = "c" * 40
RUNNER_SHA = "4" * 64
START = datetime(2000, 1, 1, tzinfo=timezone.utc)


def write_json(path, data):
    path.write_bytes(encoded(data))


def fixture_inputs(group):
    """Derive recorded-shape controls from the first five archived trials."""
    historical = group["historicalRun"]
    full = read_inputs(REPO / historical["directory"])
    summary = json.loads(full["summary.json"])
    rows = load_rows(full, 5, 12)
    captured = [pair for condition in CONDITIONS for pair in rows[condition][:300]]
    summary["config"]["trials"] = 5
    summary["gitHash"] = COMMIT
    summary["nExecutions"] = len(captured)
    summary["nSkills"] = len({trial["skillId"] for trial, _ in captured})
    trials = b"".join(encoded(trial).replace(b"\n", b"") + b"\n" for trial, _ in captured)
    candidates = b"".join(encoded(dict(candidate, step=index)).replace(b"\n", b"") + b"\n"
                          for index, (_, candidate) in enumerate(captured))
    return dict(zip(INPUT_NAMES, (trials, candidates, encoded(summary))))


def attach(root, group, item, index, inputs, worklist_sha):
    path = root / item["directory"]
    raw = root / item["artifacts"]
    raw.mkdir(parents=True)
    logs = {
        "runner.log": b"[warm-up] model loaded; first-request output discarded\n",
        "model-unload.log": f"synthetic control only: unload {index}\n".encode(),
    }
    for name, content in inputs.items():
        (raw / name).write_bytes(content)
    for name, content in logs.items():
        (path / name).write_bytes(content)
    stamp = START + timedelta(minutes=index)
    write_json(path / "launch-receipt.json", {
        "schema": "aijade.p2-r.qualification-launch.v1", "index": item["index"],
        "group": group["id"], "worklistSha256": worklist_sha,
        "sourceCommit": COMMIT, "runnerSha256": RUNNER_SHA,
        "exitCode": 0, "launchId": f"synthetic-{index:02}",
        "unloadRecordedAt": stamp.isoformat(),
        "startedAt": (stamp + timedelta(seconds=1)).isoformat(),
        "finishedAt": (stamp + timedelta(seconds=2)).isoformat(),
        "fileSha256": {name: sha(content) for name, content in {**inputs, **logs}.items()},
    })


def revise_capture(root, item, name, content):
    (root / item["artifacts"] / name).write_bytes(content)
    path = root / item["directory"] / "launch-receipt.json"
    data = json.loads(path.read_bytes())
    data["fileSha256"][name] = sha(content)
    write_json(path, data)


class DepartmentPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worklist = prepare()
        cls.inputs = {group["id"]: fixture_inputs(group) for group in cls.worklist["groups"]}

    def setUp(self):
        runtime = REPO / ".runtime"
        runtime.mkdir(exist_ok=True)
        directory = TemporaryDirectory(prefix="p2-r-prepare-controls-", dir=runtime)
        self.addCleanup(directory.cleanup)
        self.bundle = Path(directory.name)

    def build(self):
        worklist_sha = sha(encoded(self.worklist))
        write_json(self.bundle / "runner-identity.json", {
            "schema": "aijade.p2-r.runner-identity.v1",
            "worklistSha256": worklist_sha, "sourceCommit": COMMIT, "runnerSha256": RUNNER_SHA,
        })
        for group_index, group in enumerate(self.worklist["groups"]):
            for item in group["qualification"]:
                attach(self.bundle, group, item, 5 * group_index + item["index"], self.inputs[group["id"]], worklist_sha)
        for control in self.worklist["positiveControls"]:
            path = self.bundle / control["artifacts"]
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json(path, {
                "model": control["model"], "digest": control["modelDigest"], "serverVersion": "0.40.0",
                "verdict": "pass", "discriminative": True, "check": {"seedStrategy": "fixed", "runs": 5},
                "control": {"verdict": "divergent", "runs": 5, "uniqueOutputs": 5,
                            "perRun": [{"index": index, "hash": f"synthetic-{index:02}"} for index in range(5)],
                            "sampling": control["openedSampling"]},
            })

    def test_worklist_covers_archived_and_planned_population(self):
        self.assertEqual("OFFLINE_PREPARATION_ONLY", self.worklist["status"])
        self.assertEqual(0, self.worklist["formalRunsStarted"])
        slots = [slot for group in self.worklist["groups"] for slot in group["qualification"]]
        self.assertEqual(15, len({slot["directory"] for slot in slots}))
        self.assertEqual(18000, sum(slot["steps"] for slot in slots))
        self.assertEqual(21600, sum(group["historicalRun"]["steps"] for group in self.worklist["groups"]))
        self.assertEqual(21600, sum(group["regeneration"]["steps"] for group in self.worklist["groups"]))
        self.assertEqual(2, len(self.worklist["positiveControls"]))
        self.assertTrue(all("--resume-from" not in row["argvTemplate"] and "--overwrite" not in row["argvTemplate"]
                            for row in slots))

    def test_fifteen_synthetic_passes_match_without_qualifying_a_host(self):
        self.build()
        report = audit(self.bundle, self.worklist)
        self.assertEqual("CAPTURED_REPEATS_MATCH", report["status"], report["issues"])
        self.assertEqual([5, 5, 5], [len(group["completePasses"]) for group in report["groups"]])
        self.assertEqual(12, sum(len(group["comparisonsAgainstPassOne"]) for group in report["groups"]))
        self.assertTrue(report["positiveControlDiscriminationRecorded"])
        self.assertFalse(report["formalQualificationDetermined"])
        self.assertFalse(report["hardwareLogsReviewed"])

    def test_unbound_mutation_and_duplicate_launch_cannot_complete(self):
        self.build()
        members = self.worklist["groups"][0]["qualification"]
        raw = self.bundle / members[1]["artifacts"] / "summary.json"
        raw.write_bytes(raw.read_bytes() + b" ")
        path = self.bundle / members[2]["directory"] / "launch-receipt.json"
        record = json.loads(path.read_bytes())
        record["launchId"] = "synthetic-01"
        write_json(path, record)
        report = audit(self.bundle, self.worklist)
        self.assertEqual("INCOMPLETE_RECORD", report["status"])
        self.assertEqual(3, len(report["groups"][0]["completePasses"]))
        self.assertIn("launch files differ from their recorded hashes", [issue["reason"] for issue in report["issues"]])
        self.assertIn("an independent launch was already counted", [issue["reason"] for issue in report["issues"]])

    def test_bound_candidate_change_reports_first_divergence_without_raw_text(self):
        self.build()
        item = self.worklist["groups"][1]["qualification"][4]
        path = self.bundle / item["artifacts"] / "candidates.jsonl"
        rows = path.read_bytes().splitlines(keepends=True)
        changed = json.loads(rows[0])
        changed["generation"] = "synthetic changed observation, never in the report"
        rows[0] = json.dumps(changed).encode() + b"\n"
        revise_capture(self.bundle, item, "candidates.jsonl", b"".join(rows))
        report = audit(self.bundle, self.worklist)
        self.assertEqual("CAPTURED_REPEATS_DIFFER", report["status"], report["issues"])
        result = report["groups"][1]["comparisonsAgainstPassOne"][-1]["conditions"]["sv0-ef0"]
        self.assertEqual(0, result["identicalPrefixSteps"])
        self.assertEqual(["generation"], result["firstDivergence"]["differs"])
        self.assertNotIn(changed["generation"], encoded(report).decode())

    def test_duplicate_run_with_resume_is_refused_even_when_hashes_match(self):
        self.build()
        item = self.worklist["groups"][-1]["qualification"][-1]
        path = self.bundle / item["artifacts"] / "summary.json"
        summary = json.loads(path.read_bytes())
        summary["resumed"] = {"replayedSteps": 300}
        revise_capture(self.bundle, item, "summary.json", encoded(summary))
        report = audit(self.bundle, self.worklist)
        self.assertEqual("INCOMPLETE_RECORD", report["status"])
        self.assertIn("runner summary does not describe a fresh frozen run", [issue["reason"] for issue in report["issues"]])

    def test_failed_open_control_is_not_mistaken_for_discrimination(self):
        self.build()
        control = self.worklist["positiveControls"][0]
        path = self.bundle / control["artifacts"]
        data = json.loads(path.read_bytes())
        data["control"]["verdict"] = "collapsed"
        data["control"]["uniqueOutputs"] = 1
        data["verdict"] = "fail"
        for item in data["control"]["perRun"]:
            item["hash"] = "same-output"
        write_json(path, data)
        report = audit(self.bundle, self.worklist)
        self.assertEqual("CAPTURED_REPEATS_MATCH", report["status"], report["issues"])
        self.assertFalse(report["positiveControlDiscriminationRecorded"])
        self.assertFalse(report["formalQualificationDetermined"])


if __name__ == "__main__":
    unittest.main()
