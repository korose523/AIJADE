"""Constructed independent-attribution checks, not a benchmark result."""
import unittest

from analyze_product import HEADER, MARKER, observe


class AttributionTests(unittest.TestCase):
    def test_complete_partial_and_unicode_positions(self):
        store = {'a': {'Content': '鱼🐟' * 20}, 'b': {'Content': 'later item'}}
        full = HEADER + '- ' + store['a']['Content'] + '\n- ' + store['b']['Content']
        self.assertEqual(('complete', ['a', 'b']), observe(full, ['a', 'b'], store))
        cut = HEADER + '- ' + store['a']['Content'] + '\n- lat' + MARKER
        self.assertEqual(('truncated', ['a']), observe(cut, ['a', 'b'], store))
        self.assertEqual(('truncated', []), observe(HEADER + '- 鱼🐟' + MARKER, ['a', 'b'], store))

    def test_unknown_duplicates_and_unexplained_text_are_not_known_zero(self):
        store = {'a': {'Content': 'same'}, 'b': {'Content': 'same'}}
        self.assertEqual(('ambiguous-source', None), observe(HEADER+'- same', ['a', 'b'], store))
        self.assertEqual(('unexplained-block', None), observe(HEADER+'- alien', ['a'], store))
        self.assertEqual(('absent', []), observe('normal system', ['a'], store))


if __name__ == '__main__':
    unittest.main()
