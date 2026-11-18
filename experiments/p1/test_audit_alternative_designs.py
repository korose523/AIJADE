"""Offline controls for paired P1-A reporting; these tests execute no faults."""

import copy
import unittest

from audit_alternative_designs import CODE_FILE, INPUT_FILE, ROOT, audit, read_archive


class PairedReadbackTests(unittest.TestCase):
    def setUp(self):
        self.input_bytes = (ROOT / INPUT_FILE).read_bytes()
        self.inputs = read_archive(INPUT_FILE, self.input_bytes)
        self.code = read_archive(CODE_FILE, (ROOT / CODE_FILE).read_bytes())

    def test_source_bytes_reject_even_a_whitespace_change(self):
        with self.assertRaisesRegex(ValueError, "archived bytes differ"):
            read_archive(INPUT_FILE, self.input_bytes + b" ")

    def test_equal_arm_counts_do_not_hide_an_unpaired_case(self):
        unmatched = copy.deepcopy(self.inputs)
        row = next(row for row in unmatched["rows"] if row["configuration"] == "2 liberal")
        row["id"] = "unpaired"
        with self.assertRaisesRegex(ValueError, "unpaired input cases"):
            audit(unmatched, self.code)

    def test_matching_ids_do_not_hide_a_different_case_description(self):
        altered = copy.deepcopy(self.inputs)
        row = next(row for row in altered["rows"] if row["configuration"] == "2 liberal")
        row["form"] = "different case form"
        with self.assertRaisesRegex(ValueError, "differs across configurations"):
            audit(altered, self.code)

    def test_duplicate_input_row_is_not_coalesced(self):
        duplicate = copy.deepcopy(self.inputs)
        duplicate["rows"].append(duplicate["rows"][0])
        with self.assertRaisesRegex(ValueError, "duplicate or invalid input case"):
            audit(duplicate, self.code)

    def test_published_code_table_must_reconcile_with_cells(self):
        altered = copy.deepcopy(self.code)
        altered["table"]["changed unit or meaning"]["1 paper"]["detected"] = 2
        with self.assertRaisesRegex(ValueError, "disagrees with recorded cells"):
            audit(self.inputs, altered)

    def test_archived_populations_and_detection_stage_changes(self):
        result = audit(self.inputs, self.code)
        self.assertEqual(result["population"]["inputConfigurationRows"], 248)
        self.assertEqual(result["population"]["notApplicableCodeCells"], 25)
        pair = result["set1Paired"]
        self.assertTrue(pair["firstThreeDetectExactlySameCases"])
        self.assertEqual(set(pair["changedStagesAmongSharedDetections"]["2 liberal"]), {"s1"})
        self.assertEqual(set(pair["changedStagesAmongSharedDetections"]["3 contracts"]), {"s1", "s3"})
        self.assertEqual(result["inputAndData"]["1"]["1 paper"]["detectedCasesWithRowDelta"], ["o3"])


if __name__ == "__main__":
    unittest.main()
