"""Offline comparable-value canonicalization slice: ``_comparable_value`` branches.

Pure offline: no hardware, network, simulator, daemon or C-Gate I/O.
Covers the zero-direct-ref branches of
``toolkit-cli/src/cbus_toolkit/physical_programming.py:455``
(``_comparable_value``), which the offline ``PhysicalService`` fake never
exercises (its schema only emits scalar ``int`` parameters):

* numeric ``int``/``long``/``bit`` presentation canonicalization
  (``0x00`` equals ``0x0``) and single-value broadcast over
  ``array_size > 1`` plus wrong-count and non-numeric refusals;
* ``sixbit`` space-padding to eight characters plus over-length refusal;
* passthrough for other types (``string``).

Staged/fresh readback comparison calls this helper at
``physical_programming.py:1074,1077,1324,1325``; this pins the helper
directly without changing workflow semantics.
"""

from __future__ import annotations

import unittest

from cbus_toolkit.physical_programming import PhysicalParameter, PhysicalProgrammingError, _comparable_value


def param(value_type: str, array_size: int = 1) -> PhysicalParameter:
    return PhysicalParameter(
        "P", value_type, array_size, "direct", "none", "$20", (),
    )


class ComparableValueTests(unittest.TestCase):
    def test_numeric_spelling_canonicalizes(self):
        for value_type in ("int", "long", "bit"):
            with self.subTest(value_type=value_type):
                self.assertEqual(
                    _comparable_value(param(value_type), "0x00"),
                    _comparable_value(param(value_type), "0x0"),
                )
                self.assertEqual(_comparable_value(param(value_type), "0x01"), (1,))
                self.assertEqual(_comparable_value(param(value_type, 2), "$01 16"), (1, 16))

    def test_numeric_single_value_broadcasts_over_array(self):
        for value_type in ("int", "long", "bit"):
            with self.subTest(value_type=value_type):
                self.assertEqual(_comparable_value(param(value_type, 3), "0x02"), (2, 2, 2))
                self.assertEqual(_comparable_value(param(value_type, 3), "1 2 3"), (1, 2, 3))

    def test_numeric_wrong_count_and_non_numeric_refuse(self):
        with self.assertRaises(PhysicalProgrammingError):
            _comparable_value(param("int", 3), "1 2")
        with self.assertRaises(PhysicalProgrammingError):
            _comparable_value(param("int"), "not-a-number")
        with self.assertRaises(PhysicalProgrammingError):
            _comparable_value(param("int", 2), "1 2 3")

    def test_sixbit_pads_to_eight_and_refuses_over_length(self):
        self.assertEqual(_comparable_value(param("sixbit", 8), "ABC"), "ABC     ")
        self.assertEqual(_comparable_value(param("sixbit", 8), "ABCDEFGH"), "ABCDEFGH")
        # Trailing spaces are presentation only: stripped then re-padded.
        self.assertEqual(_comparable_value(param("sixbit", 8), "ABC   "), "ABC     ")
        with self.assertRaises(PhysicalProgrammingError):
            _comparable_value(param("sixbit", 8), "ABCDEFGHI")

    def test_other_types_pass_through(self):
        self.assertEqual(_comparable_value(param("string", 16), "Mixed Case"), "Mixed Case")
        self.assertEqual(_comparable_value(param("string", 16), "ABC     "), "ABC     ")


if __name__ == "__main__":
    unittest.main()
