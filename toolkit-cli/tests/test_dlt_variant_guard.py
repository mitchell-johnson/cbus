"""Tests for dlt_variant_guard scaffold (P-E). Structural only."""
import unittest

from cbus_toolkit.dlt_variant_guard import check_variant
from cbus_toolkit import dlt_variant_guard as m


class VariantTests(unittest.TestCase):
    def test_listed(self):
        table = {(("5055DL", "1.0.0")): {"notes": "pilot"}}
        self.assertEqual(m.supported_variants(table), (("5055DL", "1.0.0"),))
        got = check_variant("5055DL", "1.0.0", table)
        self.assertTrue(got.supported)
        self.assertEqual(got.behavioral_comparison, "unassessed")
        self.assertEqual(got.echo, {"notes": "pilot"})

    def test_unlisted(self):
        got = check_variant("5055DL", "9.9.9", {(("5055DL", "1.0.0")): {}})
        self.assertFalse(got.supported)

    def test_exact_no_ranges(self):
        table = {(("M", "1.0")): {}}
        self.assertFalse(check_variant("M", "1.0.0", table).supported)
        self.assertFalse(check_variant("m", "1.0", table).supported)

    def test_bad(self):
        with self.assertRaises(ValueError):
            check_variant("", "1.0", {})
        with self.assertRaises((TypeError, ValueError)):
            m.supported_variants("xx")


if __name__ == "__main__":
    unittest.main()
