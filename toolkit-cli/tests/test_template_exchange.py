"""Tests for template_exchange scaffold (issue #11 box 5). Structural only."""
import unittest

from cbus_toolkit.template_exchange import (
    check_identity_preservation,
    plan_exchange,
)

IDENT = {"serial": "S1", "address": 3}


class PlanTests(unittest.TestCase):
    def test_export_import_steps(self):
        for direction, middle in (("export", "read_template"),
                                  ("import", "stage_template")):
            with self.subTest(direction=direction):
                got = plan_exchange(direction, "KEY1", {"KEY1"}, IDENT, {})
                self.assertEqual(
                    got.steps,
                    ("validate_identity", "check_profile", middle,
                     "verify_identity_preserved"),
                )
                self.assertEqual(got.behavioral_comparison, "unassessed")
                self.assertEqual(got.echo["identity"], IDENT)

    def test_bad_direction_profile(self):
        with self.assertRaises(ValueError):
            plan_exchange("sync", "KEY1", {"KEY1"}, IDENT, {})
        with self.assertRaises(ValueError):
            plan_exchange("import", "NOPE", {"KEY1"}, IDENT, {})
        with self.assertRaises(ValueError):
            plan_exchange("import", "", {"KEY1"}, IDENT, {})

    def test_bad_identity_attrs(self):
        for bad in ({}, {"serial": "S"}, {"serial": "", "address": 1},
                    {"serial": "S", "address": -1},
                    {"serial": "S", "address": True}):
            with self.subTest(bad=repr(bad)[:24]):
                with self.assertRaises((TypeError, ValueError)):
                    plan_exchange("import", "KEY1", {"KEY1"}, bad, {})
        with self.assertRaises(TypeError):
            plan_exchange("import", "KEY1", {"KEY1"}, IDENT, [1])


class IdentityTests(unittest.TestCase):
    def test_preserved(self):
        got = check_identity_preservation(IDENT, dict(IDENT))
        self.assertTrue(got.ok)

    def test_differs_no_reason(self):
        got = check_identity_preservation(
            IDENT, {"serial": "S2", "address": 3})
        self.assertFalse(got.ok)

    def test_differs_with_reason(self):
        got = check_identity_preservation(
            IDENT, {"serial": "S2", "address": 3}, "replacement unit")
        self.assertTrue(got.ok)
        self.assertIn("replacement", got.note)


if __name__ == "__main__":
    unittest.main()
