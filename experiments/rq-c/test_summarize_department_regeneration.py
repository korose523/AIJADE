"""Archive readback and simulated launcher controls for the read-only paired report."""

from datetime import timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import launch_department_regeneration as launch
import summarize_department_regeneration as statistics
import test_launch_department_regeneration as fixtures
from prepare_department_regeneration import DEPARTMENT_DRAFT_SHA, REPO, encoded, prepare, sha
from test_prepare_department_regeneration import COMMIT, START, fixture_inputs


class DivergentFixture(fixtures.FixtureRuntime):
    def run(self, argv, log):
        code = super().run(argv, log)
        if argv[argv.index("--model") + 1] == "llama3.1:8b":
            prefix = Path(argv[argv.index("--out") + 1])
            path = prefix / "rq-c-s42-ollama-t30-r5/candidates.jsonl"
            rows = path.read_bytes().splitlines(keepends=True)
            first = json.loads(rows[0])
            first["generation"] = "synthetic visible difference"
            rows[0] = compact(first)
            path.write_bytes(b"".join(rows))
        return code


def compact(row):
    return (json.dumps(row, separators=(",", ":")) + "\n").encode()


class DepartmentStatisticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worklist = prepare()
        cls.archival = statistics.report(cls.worklist)
        runtime = REPO / ".runtime"
        runtime.mkdir(exist_ok=True)
        directory = TemporaryDirectory(prefix="p2-r-statistics-controls-", dir=runtime)
        cls.addClassCleanup(directory.cleanup)
        cls.bundle = Path(directory.name).resolve() / "regeneration"
        synthetic = DivergentFixture(cls.worklist, {})
        cls.worklist_sha = sha(encoded(cls.worklist))
        approval = {
            "sourceCommit": COMMIT,
            "ollamaUrl": "http://synthetic.invalid:11434",
            "ollamaVersion": fixtures.VERSION,
            "reviewedDraftSha256": DEPARTMENT_DRAFT_SHA,
            "worklistSha256": cls.worklist_sha,
            "logHistorySince": launch.stamp(START),
            "notAfter": launch.stamp(fixtures.END),
            "host": fixtures.HOST,
            "build": {"rqcDll": "synthetic-rqc.dll", "files": {"synthetic-rqc.dll": "3" * 64}},
        }
        tools = {name: Path(directory.name).resolve() / name for name in ("dotnet", "rqcDll", "substrateDll")}
        qualification = {
            "sha256": "4" * 64,
            "finalLogs": fixtures.capture_raw(START, START + timedelta(seconds=2),
                                             [("system", {"id": "historical", "at": launch.stamp(START + timedelta(seconds=1)),
                                                          "record": "synthetic event"})]),
        }
        receipt = launch.perform("regeneration", cls.bundle, approval, "5" * 64, tools,
                                 cls.worklist, synthetic, qualification)
        if receipt["status"] != "REGENERATION_EVIDENCE_COMPLETE":
            raise AssertionError(receipt)
        cls.phase = cls.bundle / "phase-result.json"
        cls.pin = sha(cls.phase.read_bytes())

    def test_all_three_archives_reproduce_the_existing_analysis(self):
        self.assertEqual("RETAINED_ARCHIVE_SELF_CHECK", self.archival["scope"])
        self.assertEqual(0, self.archival["formalRunsStartedByReport"])
        self.assertEqual("NOT_RUN_BY_THIS_REPORT", self.archival["exploratoryOracleRetally"])
        groups = self.archival["groups"]
        self.assertEqual([7200, 7200, 7200], [row["archived"]["executions"] for row in groups.values()])
        self.assertEqual([1519, 1602, 1500], [row["archived"]["skills"] for row in groups.values()])
        self.assertEqual([56, 55, 49], [row["archived"]["distinctJudgedCandidates"]["candidates"] for row in groups.values()])
        self.assertTrue(all(row["archiveReadbackMatches"] for row in groups.values()))

    def test_reads_simulated_launcher_records_and_redacts_the_divergent_values(self):
        report = statistics.report(self.worklist, self.bundle, self.pin)
        self.assertEqual("RECORDED_REGENERATION_COMPARISON", report["scope"])
        self.assertEqual(self.pin, report["regenerationPhaseReceiptSha256"])
        self.assertEqual(COMMIT, report["regenerationSourceCommit"])
        self.assertEqual(0, report["formalRunsStartedByReport"])
        groups = report["groups"]
        for row in groups.values():
            self.assertEqual(row["archived"], row["regenerated"])
        change = groups["second-family"]["alignment"]
        self.assertEqual("DIFFERENT", change["status"])
        first = change["conditions"]["sv0-ef0"]["firstDivergence"]
        self.assertEqual({"step", "skill", "differs"}, set(first))
        self.assertEqual((0, ["generation"]), (first["step"], first["differs"]))
        self.assertNotIn(b"synthetic visible difference", encoded(report))
        self.assertEqual(self.pin, sha(self.phase.read_bytes()))

    def test_wrong_pin_and_incomplete_phase_are_refused(self):
        with self.assertRaisesRegex(ValueError, "file identity differs"):
            statistics.verified_phase(self.bundle, "6" * 64, self.worklist)
        original = self.phase.read_bytes()
        self.addCleanup(self.phase.write_bytes, original)
        failed = json.loads(original)
        failed["status"] = "INCOMPLETE_DEPARTMENT_EVIDENCE"
        raw = encoded(failed)
        self.phase.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "completed regeneration"):
            statistics.verified_phase(self.bundle, sha(raw), self.worklist)

    def test_changed_bound_comparator_is_refused(self):
        entry = self.bundle / self.worklist["groups"][0]["regeneration"]["directory"] / "archive-comparison.json"
        original = entry.read_bytes()
        self.addCleanup(entry.write_bytes, original)
        entry.write_bytes(original + b"\n")
        with self.assertRaisesRegex(ValueError, "bundle files differ"):
            statistics.verified_phase(self.bundle, self.pin, self.worklist)

    def test_exact_counters_do_not_hide_a_changed_reuse_identity(self):
        inputs = fixture_inputs(self.worklist["groups"][0])
        records = inputs["candidates.jsonl"].splitlines(keepends=True)
        for i, raw in enumerate(records):
            row = json.loads(raw)
            if row["reused"]:
                row["code"] += " /* synthetic reuse mismatch */"
                records[i] = compact(row)
                break
        else:
            self.fail("control needs a previously generated skill")
        inputs["candidates.jsonl"] = b"".join(records)
        with self.assertRaisesRegex(ValueError, "code changed within a skill"):
            statistics.summarize_records(inputs)


if __name__ == "__main__":
    unittest.main()
