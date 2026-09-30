"""Independent original PP/model mapping receipt; no GUI or hardware claim."""
import hashlib
import itertools
import json
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/classic-dlt-brightness-original.json'


def expected_case(raw33, raw34):
    duration = raw33 & 15
    model = {'EnableNightlightControl': int(bool(raw34 & 128)),
             'FirstKeyThrowAway': int(bool(raw34 & 16)),
             'KeyPressBrightnessDuration': duration, 'KeyPressBrightnessLevel': raw33 >> 4,
             'NightlightEnabled': 1, 'NightlightForced': int(not bool(raw34 & 1)),
             'EnablePageFallback': int(bool(raw34 & 4) and duration > 0),
             'EnableIndicatorPressed': int(bool(raw34 & 8) and duration > 0),
             'EnableNightlightOnToggle': int(bool(raw34 & 64)),
             'EnableNightlightOnKeys': int(bool(raw34 & 32))}
    return {'byte33': raw33, 'byte34': raw34, 'loaded': model,
            'saved_byte33': raw33, 'saved_byte34': raw34 & (0xF2 if duration == 0 else 0xFE)}


class BrightnessOriginalEvidenceTests(unittest.TestCase):
    def test_exhaustive_receipt_matches_independent_byte_mapping(self):
        report = json.loads(FIXTURE.read_text())
        self.assertEqual(report['format'], 'cbus-classic-dlt-brightness-original-v1')
        rows = [expected_case(raw33, 0xFD) for raw33 in range(256)]
        rows.extend(expected_case(0xF0 | duration, raw34)
                    for duration, raw34 in itertools.product((0, 1, 2, 15), range(256)))
        digest = hashlib.sha256(json.dumps(rows, separators=(',', ':'), sort_keys=True).encode()).hexdigest()
        observations = report['observations']
        self.assertEqual(observations['cases'], 1280)
        self.assertEqual(observations['numeric_cases'], 256)
        self.assertEqual(observations['flag_cases'], 1024)
        self.assertEqual(observations['cases_sha256'], digest)
        self.assertEqual(observations['selected'],
                         [row for row in rows[256:] if row['byte34'] in (0, 1, 0xFC, 0xFD, 0xFF)])

    def test_layout_has_no_overlapping_field_and_pins_classic_ancestry(self):
        report = json.loads(FIXTURE.read_text())
        fields = report['parameter_layouts']
        self.assertEqual(fields['TimerDuration']['BitAddress'], '0')
        self.assertEqual(fields['IndicatorPressedLevel']['BitAddress'], '4')
        for name in ('TimerDuration', 'IndicatorPressedLevel'):
            self.assertEqual(fields[name]['Address'], '$33')
            self.assertEqual(fields[name]['BitSize'], '4')
            self.assertEqual(fields[name]['MinValue'], '$00')
            self.assertEqual(fields[name]['MaxValue'], '$0F')
        bits = [int(field['BitAddress']) for field in fields.values() if field['Address'] == '$34']
        self.assertEqual(sorted(bits), [0, 2, 3, 4, 5, 6, 7])
        self.assertTrue(report['family_slots']['0x210']['symbol'].endswith('.IsNeoDLT'))
        self.assertTrue(report['family_slots']['0x1f4']['symbol'].endswith('.IsNeoClassic'))
        self.assertTrue(report['family_slots']['0x20c']['symbol'].endswith('.IsNeoMultisensor'))


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE') and os.environ.get('CBUS_UNITSPEC_DIR'),
                     'requires pinned original Toolkit EXE/MAP and decoded specs')
class BrightnessOriginalReplayTests(unittest.TestCase):
    def test_original_fragments_reproduce_retained_receipt(self):
        from research.classic_dlt_brightness_original import inspect
        executable = Path(os.environ['CBUS_TOOLKIT_EXE'])
        symbols = Path(os.environ.get('CBUS_TOOLKIT_MAP', executable.with_suffix('.map')))
        report = inspect(executable, symbols, Path(os.environ['CBUS_UNITSPEC_DIR']))
        self.assertEqual(report, json.loads(FIXTURE.read_text()))


if __name__ == '__main__':
    unittest.main()
