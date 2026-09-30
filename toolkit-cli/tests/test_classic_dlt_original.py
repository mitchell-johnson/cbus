"""Pinned source evidence checks; original replay is explicitly opted in."""
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/classic-dlt-controls-original.json'


class ClassicDltOriginalEvidenceTests(unittest.TestCase):
    def test_original_boolean_domains_and_dedicated_save_side_effects(self):
        report = json.loads(FIXTURE.read_text())
        self.assertEqual(report['format'], 'cbus-classic-dlt-controls-original-v1')
        self.assertEqual(len(report['observations']), 10)
        for row in report['observations']:
            with self.subTest(row=row):
                if row['operation'] == 'load':
                    self.assertIs(row['result']['blocked'], not row['input_enabled'])
                elif row['operation'] == 'save':
                    expected = not row['input_blocked'] if row['database'] else True
                    self.assertIs(row['result']['enabled'], expected)
                else:
                    calls = row['result']['calls']
                    if not row['input_blocked']:
                        self.assertEqual(calls, [])
                        continue
                    expected = ['SetOne', 'Save']
                    if not row['in_session']:
                        expected = ['Lock', 'Start', 'Load', *expected, 'End', 'Unlock']
                    self.assertEqual([call['operation'] for call in calls], expected)
                    self.assertEqual(next(call for call in calls if call['operation'] == 'SetOne'), {
                        'operation': 'SetOne', 'parameter': 'EnableDynamicLabels',
                        'value': '0', 'database': False})

    def test_native_receipt_matches_source_polarity_and_preserved_bits(self):
        original = json.loads(FIXTURE.read_text())
        native = json.loads((FIXTURE.parent / 'classic-dlt-controls-native.json').read_text())
        profiles = json.loads((FIXTURE.parent / 'dlt-profile-facts.json').read_text())
        self.assertTrue(native['passed'])
        self.assertTrue(native['project_save_close_reload_passed'])
        self.assertFalse(native['physical_hardware_verified'])
        self.assertFalse(native['original_full_form_save_executed'])
        self.assertEqual(native['specs']['I_DLT.xml'], original['source']['I_DLT.xml_sha256'])
        for name, digest in native['specs'].items():
            if name in profiles['specifications']:
                self.assertEqual(digest, profiles['specifications'][name]['sha256'])
        self.assertEqual(len(native['cases']), 5)
        self.assertEqual({case['unit_type'] for case in native['cases']}, {'KEYBL5', 'KEYML5', 'KEYDL4'})
        for case in native['cases']:
            with self.subTest(unit=case['unit_type'], firmware=case['firmware']):
                self.assertEqual([step['block_dynamic_updates'] for step in case['steps']], [True, False, True])
                for step in case['steps']:
                    self.assertEqual(step['raw_before'] ^ step['raw_after'], 0x40)
                    self.assertIs(bool(step['raw_after'] & 0x40), not step['block_dynamic_updates'])
                    self.assertTrue(step['all_other_pp_preserved'])

    def test_probe_rejects_unpinned_inputs_before_emulation(self):
        from research.classic_dlt_controls_original import ClassicControlsProbe
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'untrusted.bin'
            path.write_bytes(b'not a vendor executable')
            with self.assertRaisesRegex(ValueError, 'pinned Toolkit'):
                ClassicControlsProbe(path, path)


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE') and os.environ.get('CBUS_UNITSPEC_DIR'),
                     'requires pinned original Toolkit EXE/MAP and decoded specs')
class ClassicDltOriginalReplayTests(unittest.TestCase):
    def test_fresh_original_instructions_match_retained_evidence(self):
        from research.classic_dlt_controls_original import inspect
        executable = Path(os.environ['CBUS_TOOLKIT_EXE'])
        symbols = Path(os.environ.get('CBUS_TOOLKIT_MAP', executable.with_suffix('.map')))
        specification = Path(os.environ['CBUS_UNITSPEC_DIR']) / 'I_DLT.xml'
        self.assertEqual(inspect(executable, symbols, specification), json.loads(FIXTURE.read_text()))


if __name__ == '__main__':
    unittest.main()
