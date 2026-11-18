import unittest

from audit_langchain_scorer_policy_interaction import CELL_PAIRS, assess_stage


def fixture():
    primary = {(dialogue, 0): {"evidence": ["gold-a", "gold-b"]} for dialogue in range(10)}
    output = {(c, q, policy, scorer): () for c, q in primary for policy, scorer in CELL_PAIRS}
    return primary, output


class ArchivedInteractionControls(unittest.TestCase):
    def test_policy_under_relevance_is_subtracted(self):
        primary, output = fixture()
        for c, q in primary:
            output[c, q, "on", "relevance"] = ("gold-a",)
        result = assess_stage(output, primary, primary)
        self.assertEqual(result["metrics"]["hitAny"]["interaction"]["mean"], -1)
        self.assertEqual(result["metrics"]["annotatedSourceFraction"]["interaction"]["mean"], -0.5)
        self.assertEqual(result["hitTransitions"]["relevance"]["onOnly"], 10)
        self.assertEqual(result["hitTransitions"]["own"]["neither"], 10)

    def test_questions_are_averaged_within_dialogue_before_contrast(self):
        primary, output = fixture()
        for q in range(1, 20):
            primary[0, q] = {"evidence": ["gold-a", "gold-b"]}
            for policy, scorer in CELL_PAIRS:
                output[0, q, policy, scorer] = ()
        for q in range(20):
            output[0, q, "on", "own"] = ("gold-a",)
        result = assess_stage(output, primary, primary)
        self.assertEqual(result["metrics"]["hitAny"]["interaction"]["mean"], 0.1)
        self.assertEqual(result["metrics"]["annotatedSourceFraction"]["interaction"]["mean"], 0.05)
        self.assertEqual(result["hitTransitions"]["own"]["onOnly"], 20)

    def test_missing_condition_is_refused(self):
        primary, output = fixture()
        del output[0, 0, "off", "relevance"]
        with self.assertRaises(KeyError):
            assess_stage(output, primary, primary)


if __name__ == "__main__":
    unittest.main()
