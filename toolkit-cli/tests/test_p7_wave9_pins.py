"""Wave 9 narrow offline pin for P7.01 (DALI typed deployment targets).

Pins the pure-offline ``dali_target`` gateway grammar in
``dali_commissioning.py``: ``//PROJECT/NETWORK/p/UNIT`` with network 0..255,
unit 1..254, and canonical integer normalization. No daemon, journal,
hardware, or native service is involved.
"""
from __future__ import annotations

import unittest

from cbus_toolkit.dali_commissioning import dali_target


class DaliTargetGrammarWave9Tests(unittest.TestCase):
    """dali_commissioning.dali_target: admit/normalize/reject without I/O."""

    def test_boundary_targets_pass_through(self):
        self.assertEqual(dali_target("//TEST/254/p/20"), "//TEST/254/p/20")
        self.assertEqual(dali_target("//A1/0/p/1"), "//A1/0/p/1")
        self.assertEqual(dali_target("//ABCDEFGH/255/p/254"), "//ABCDEFGH/255/p/254")

    def test_zero_padded_numerics_normalize_to_canonical(self):
        self.assertEqual(dali_target("//P/007/p/003"), "//P/7/p/3")
        self.assertEqual(dali_target("//TEST/01/p/01"), "//TEST/1/p/1")

    def test_out_of_range_network_or_unit_rejected(self):
        for bad in ("//TEST/256/p/20", "//TEST/254/p/0", "//TEST/254/p/255"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "0\\.\\.255, unit 1\\.\\.254"):
                dali_target(bad)

    def test_malformed_shapes_and_non_text_rejected(self):
        for bad in ("//TOOLONGPROJ/1/p/1", "//TEST/1/20", "TEST/1/p/1",
                    "//TEST/1/p/", "//test-name/1/p/1", None, 123, True):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "DALI gateway must be"):
                dali_target(bad)


if __name__ == "__main__":
    unittest.main()
