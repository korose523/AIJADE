"""Offline check that the per-case path table reproduces Table 7.3 and the propagation count of Section 7.3."""
import unittest

from case_paths import build


class CasePaths(unittest.TestCase):
    def test_totals_and_propagation(self):
        report = build()
        self.assertEqual(len(report["cases"]), 40)
        self.assertEqual(report["totals"], {"C1": {"wrongPromotions": 12, "wrongReuses": 8},
                                            "C2": {"wrongPromotions": 0, "wrongReuses": 0}})
        self.assertEqual(report["propagation"], {"c1WrongPromotionsReusedInRound2": 8,
                                                 "c1WrongReusesWithoutAC1WrongPromotion": 0,
                                                 "casesStoppedInRound2ByC2AndMissedByC1": 0})

    def test_each_case_type_follows_one_path(self):
        paths = {}
        for c in build()["cases"]:
            paths.setdefault(c["window"], set()).add((c["C1"]["round1"], c["C1"]["round2"], c["C2"]["round1"], c["C2"]["round2"]))
        self.assertEqual(len(paths), 10)
        self.assertTrue(all(len(v) == 1 for v in paths.values()))


if __name__ == "__main__":
    unittest.main()
