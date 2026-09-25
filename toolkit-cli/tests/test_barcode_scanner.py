"""Tests for barcode_scanner spec scaffold (issue #11 box 11).

Structural RED/GREEN only. No vendor oracle, no parity claims.
"""
import unittest

from cbus_toolkit.barcode_scanner import (
    ParsedPayload,
    decide_action,
    parse_payload,
)


class ParsePayloadTests(unittest.TestCase):
    def test_serial_shape_preserved_verbatim(self):
        with self.subTest("case preserved"):
            got = parse_payload("CBUS:AbC-123")
            self.assertEqual(got.kind, "serial")
            self.assertEqual(got.opaque, "AbC-123")
            self.assertEqual(got.vendor_comparison, "unassessed")

    def test_whitespace_stripped_then_shaped(self):
        got = parse_payload("  CBUS:X1 \t")
        self.assertEqual((got.kind, got.opaque), ("serial", "X1"))

    def test_unknown_shapes(self):
        for raw in ["hello", "cbus:X1", "CBUS:", "CBUS:" + "Y" * 65]:
            with self.subTest(raw=raw[:12]):
                got = parse_payload(raw)
                self.assertEqual(got.kind, "unknown")

    def test_empty_rejected(self):
        for raw in ["", "   ", "\t\r\n"]:
            with self.subTest(raw=repr(raw)):
                with self.assertRaises(ValueError):
                    parse_payload(raw)

    def test_non_str_rejected(self):
        for raw in [None, 123, b"CBUS:X"]:
            with self.subTest(raw=repr(raw)):
                with self.assertRaises(TypeError):
                    parse_payload(raw)


class DecideActionTests(unittest.TestCase):
    def test_decision_table(self):
        cases = [
            ("serial", "found", "select_existing"),
            ("serial", "absent", "propose_create"),
            ("serial", "ambiguous", "reject"),
            ("unknown", "found", "reject"),
            ("unknown", "absent", "reject"),
            ("unknown", "ambiguous", "reject"),
        ]
        for kind, inv, want in cases:
            with self.subTest(kind=kind, inv=inv):
                got = decide_action(
                    ParsedPayload(kind=kind, opaque="O"), inv
                )
                self.assertEqual(got.decision, want)
                self.assertTrue(got.reason)
                self.assertEqual(got.vendor_comparison, "unassessed")

    def test_bad_inventory_fact_rejected(self):
        with self.assertRaises(ValueError):
            decide_action(ParsedPayload(kind="serial", opaque="O"), "maybe")

    def test_non_parsed_rejected(self):
        with self.assertRaises(TypeError):
            decide_action("CBUS:O", "found")

    def test_extra_echo_value_not_alias(self):
        extra = {"note": {"a": [1]}}
        got = decide_action(
            ParsedPayload(kind="serial", opaque="O"), "found", extra
        )
        self.assertEqual(got.echo, extra)
        self.assertIsNot(got.echo, extra)
        self.assertIsNot(got.echo["note"], extra["note"])
        extra["note"]["a"].append(99)
        self.assertEqual(got.echo["note"], {"a": [1]})


if __name__ == "__main__":
    unittest.main()
