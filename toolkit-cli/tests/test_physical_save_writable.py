"""Offline P4.04 special-handling slice: ``_save_writable`` branch matrix.

Pure unit test, no hardware, no network, no binaries or daemons. Covers the
four branches of ``physical_programming._save_writable`` (physical_programming.py:314),
which the offline ``PhysicalService`` fake never exercises (its schema always
emits ``<Protection>none</Protection>``). The interop matrix covers the same
contract with scripted-PCI/cmqttd; this is the offline unit counterpart.
"""

import unittest

from cbus_toolkit.physical_programming import PhysicalParameter, _save_writable


def param(value_type, protection):
    return PhysicalParameter(
        "P", value_type, 1, "direct", protection, "$20", (),
    )


class SaveWritableTests(unittest.TestCase):
    def test_factory_bit_is_written(self):
        self.assertTrue(_save_writable(param("bit", "factory")))

    def test_factory_non_bit_is_skipped(self):
        for value_type in ("int", "long", "string", "sixbit"):
            with self.subTest(value_type=value_type):
                self.assertFalse(_save_writable(param(value_type, "factory")))

    def test_special_is_skipped_including_bit(self):
        for value_type in ("int", "bit", "long", "string", "sixbit"):
            with self.subTest(value_type=value_type):
                self.assertFalse(_save_writable(param(value_type, "special")))

    def test_ordinary_protections_are_written(self):
        for protection in ("none", "checksum", "lock"):
            for value_type in ("int", "bit"):
                with self.subTest(protection=protection, value_type=value_type):
                    self.assertTrue(_save_writable(param(value_type, protection)))


if __name__ == "__main__":
    unittest.main()
