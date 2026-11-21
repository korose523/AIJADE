"""Offline tests for the two-layer P2-R report, on synthetic records and on the retained host-2 deviation run."""
import json
from pathlib import Path
import tempfile
import unittest

from two_layer_report import compare, load

HERE = Path(__file__).resolve().parent


def write_run(directory, rows):
    directory.mkdir(parents=True)
    with open(directory / "trials.jsonl", "w", encoding="utf-8") as t, open(directory / "candidates.jsonl", "w", encoding="utf-8") as c:
        for i, (task, code, ok, verdict) in enumerate(rows):
            skill = f"s{i}-{task}"
            t.write(json.dumps({"skillId": skill, "taskId": task, "execOk": ok, "selfVerdict": verdict}) + "\n")
            c.write(json.dumps({"skillId": skill, "execOk": ok, "code": code}) + "\n")


class TwoLayerReport(unittest.TestCase):
    def test_synthetic_layers(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, r = Path(tmp) / "a", Path(tmp) / "r"
            write_run(a, [("t1", "x", True, "pass"), ("t1", "x", True, "pass"), ("t2", "y", False, "fail"),
                          ("t2", "z", True, "pass"), ("t2", "z", True, "fail")])
            write_run(r, [("t1", "x", True, "pass"), ("t2", "y", True, "fail"), ("t2", "w", False, None),
                          ("t2", "z", True, "pass"), ("t1", "y", True, "fail")])
            out = compare(load(a), load(r))
        gen, judge = out["generationLayer"], out["judgmentLayer"]
        self.assertEqual(gen["distinctPrograms"], {"archived": 3, "regenerated": 5})
        self.assertEqual(gen["regeneratedProgramsIdenticalToAnArchivedProgram"], 3)  # same code in another task does not count
        self.assertEqual(judge["oracleOnIdenticalPrograms"], {"sameVerdict": 2, "conflicting": 1})
        self.assertEqual(judge["selfVerdictOnIdenticalPrograms"],
                         {"programsJudgedInBoth": 3, "tiedInEitherRun": 1, "sameMajority": 2, "differentMajority": 0})
        self.assertEqual(gen["taskPassRates"]["t2"], {"archived": "2/3", "regenerated": "2/3"})

    def test_mismatched_records_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "bad"
            write_run(run, [("t1", "x", True, None)])
            with open(run / "candidates.jsonl", "a", encoding="utf-8") as c:
                c.write(json.dumps({"skillId": "extra", "execOk": True, "code": "x"}) + "\n")
            with self.assertRaises(ValueError):
                load(run)

    def test_reproduces_the_host2_verification(self):
        reference = json.loads((HERE / "host2-local-20261119/mac-verification/verification.json").read_text(encoding="utf-8"))
        pairs = {"template-a": "template-gpu/A", "template-b": "template-gpu/B", "second-family": "family-gpu"}
        for name, archive in pairs.items():
            out = compare(load(HERE / archive / "rq-c-s42-ollama-t30-r5"),
                          load(HERE / "host2-local-20261119/delivered/regeneration" / name / "rq-c-s42-ollama-t30-r5"))
            ref = reference["regenerationVsArchive"][name]
            self.assertEqual(out["judgmentLayer"]["oracleOnIdenticalPrograms"], ref["oracleOnIdenticalPrograms"])
            sv = out["judgmentLayer"]["selfVerdictOnIdenticalPrograms"]
            self.assertEqual((sv["programsJudgedInBoth"], sv["sameMajority"]),
                             (ref["selfVerdictOnIdenticalPrograms"]["programs"], ref["selfVerdictOnIdenticalPrograms"]["sameMajority"]))


if __name__ == "__main__":
    unittest.main()
