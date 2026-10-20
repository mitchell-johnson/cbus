"""P8.02 wave-16 narrow offline pin for #56 (key report enumeration guards).

Pins pure-offline enumeration guards in
``cbus_toolkit.project_documentation_devices.classic_key_lines`` only:
mismatched ``macros``/``key_prefixes`` and ``block_applications`` lengths
are refused before any row is rendered, while matching metadata renders.
No server, hardware, GUI, vendor EXE, eDLT, firmware, or parity-register
claim; #56 stays OPEN.

Each edge below had zero prior refs in ``tests/`` (no test referenced the
``key report metadata count mismatch`` / ``block application count
mismatch`` guards or the ``key_prefixes`` report parameter).
"""

from __future__ import annotations

import unittest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit import project_documentation_devices as devices
from cbus_toolkit.macros import STAGES


def _pp(commands=((13, 0, 0, 0),)):
    return {"Application": [56, 255], "DebounceTime": [2], "LongPressTime": [63],
            "RampRate": [0, 1], "GroupAddress": [1, 2, 255, 255],
            "BlockAllocation": [1] * len(commands),
            "LightLevelStore1": [128, 255, 1, 0], "LightLevelStore2": [0, 254, 2, 3],
            "TimerHighByte": [14, 255, 0, 0], "TimerLowByte": [77, 255, 60, 0],
            "TimerExpiryCommand": [12, 8, 0, 15],
            **{stage: [commands[key][index] for key in range(len(commands))]
               for index, stage in enumerate(STAGES)}}


def _network():
    return doc.Network(254, "Local", "", "", [doc.Application(56, "Lighting", "", [
        doc.Group(1, "Kitchen", "", []), doc.Group(2, "Hall", "", [])])], [])


def _data(commands=((13, 0, 0, 0),)):
    unit = doc.Unit(12, "Key", "KEY1", "", "", "1.2.00", "",
                    {name: " ".join(map(str, values)) for name, values in _pp(commands).items()}, {})
    return devices.classic_key_data(unit)


class KeyReportMetadataGuardWave16Tests(unittest.TestCase):
    def test_macros_count_mismatch_refused_before_render(self):
        # Next: native report-manager ordering/whole-export equivalence stays open.
        data = _data()
        with self.assertRaisesRegex(ValueError, "key report metadata count mismatch"):
            devices.classic_key_lines(_network(), data, macros=[])
        with self.assertRaisesRegex(ValueError, "key report metadata count mismatch"):
            devices.classic_key_lines(_network(), data, macros=[(0, "On"), (0, "On")])

    def test_key_prefixes_count_mismatch_refused_before_render(self):
        # Next: native key-prefix text/encoding selection stays open.
        data = _data()
        with self.assertRaisesRegex(ValueError, "key report metadata count mismatch"):
            devices.classic_key_lines(_network(), data, key_prefixes=["A", "B"])
        with self.assertRaisesRegex(ValueError, "key report metadata count mismatch"):
            devices.classic_key_lines(_network(), data, key_prefixes=[])

    def test_block_applications_count_mismatch_refused_before_render(self):
        # Next: per-block application topology/model admission stays open.
        data = _data()
        self.assertEqual(len(data.groups), 4)
        with self.assertRaisesRegex(ValueError, "block application count mismatch"):
            devices.classic_key_lines(_network(), data, block_applications=[56, 56])
        with self.assertRaisesRegex(ValueError, "block application count mismatch"):
            devices.classic_key_lines(_network(), data, block_applications=[56] * 5)

    def test_matching_report_metadata_renders_with_prefix(self):
        # Control: omitted metadata and exactly matching lengths pass the guards.
        data = _data()
        lines = devices.classic_key_lines(_network(), data)
        self.assertIn("<td>On</td>", lines[9])
        prefixed = devices.classic_key_lines(
            _network(), data, macros=[(0, "On")], key_prefixes=["K"],
            block_applications=[56, 56, 56, 56])
        self.assertIn("<td>K1</td>", prefixed[9])
        self.assertIn("<td>On</td>", prefixed[9])


if __name__ == "__main__":
    unittest.main()
