import unittest
from totals import total
class Totals(unittest.TestCase):
    def test_duplicates(self): self.assertEqual(total([2,2,3]),7)
    def test_negative(self): self.assertEqual(total([-2,2,2]),2)
    def test_empty(self): self.assertEqual(total([]),0)
    def test_distinct(self): self.assertEqual(total([1,2,3]),6)
