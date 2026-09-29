"""Original updater argv oracle: offline guards plus an explicitly gated Mono run."""
import base64
import os
from pathlib import Path
import platform
import unittest
from unittest.mock import patch

from research import firmware_update_oracle as oracle
from cbus_toolkit import firmware_update_plan as plans

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'research/fixtures/firmware-update-packages/eDLTFirmware_1.7.0.zip'


def encoded(*rows):
    return ''.join('\t'.join([category] + [base64.b64encode(value.encode()).decode() for value in values]) + '\n'
                   for category, *values in rows)


class OracleGuardTests(unittest.TestCase):
    def case(self, plan, argv, **overrides):
        extracted = {str(index): {'entry': name, 'bytes': 1, 'sha256': 'a'}
                     for index, name in enumerate(plan['package']['extracted_entries'])}
        rows = [{'argv': value, 'file_sha256': 'a', 'file_bytes': step.get('bytes', 1),
                 'gap_seconds': step['delay_before_ms'] / 1000} for value, step in zip(argv, plan['dfuprog_steps'])]
        return {'fail_at': None, 'dfuprog': rows, 'extracted': extracted, 'native_variant': plan['variant'],
                'package_version': plan['package']['version'], 'temporary_files_left': [], 'serial_commands': [],
                'result': ('upgrade', 'returned'), **overrides}

    def test_compare_detects_argv_file_delay_and_result_differences(self):
        plan = plans.update_plan(PACKAGE, variant='TivaPCI', force_font=True)
        for step in plan['dfuprog_steps']:
            step['bytes'] = 1
        good = self.case(plan, [step['argv'] for step in plan['dfuprog_steps']])
        checks = oracle.compare(good, plan)
        self.assertTrue(all(checks.values()), checks)
        swapped = self.case(plan, [step['argv'] for step in plan['dfuprog_steps']][::-1])
        self.assertFalse(oracle.compare(swapped, plan)['argv_sequence'])
        early = self.case(plan, [step['argv'] for step in plan['dfuprog_steps']])
        early['dfuprog'][1]['gap_seconds'] = 1.0
        self.assertFalse(oracle.compare(early, plan)['delays'])
        other_file = self.case(plan, [step['argv'] for step in plan['dfuprog_steps']])
        other_file['dfuprog'][2]['file_sha256'] = 'b'
        self.assertFalse(oracle.compare(other_file, plan)['file_arguments'])
        failed = self.case(plan, [step['argv'] for step in plan['dfuprog_steps']][:2], fail_at=2,
                           result=('exception', 'Exception|Unable to clear flash memory for font data installation (exit code 3).|False'))
        self.assertTrue(oracle.compare(failed, plan)['failure_stop'])
        failed['result'] = ('upgrade', 'returned')
        self.assertFalse(oracle.compare(failed, plan)['failure_stop'])
        self.assertFalse(oracle.compare(good, plan, {'edlt_fontdata_1.0.0.bin': 'z'})['decrypt_adapter_hashes'])

    def test_probe_output_is_strictly_framed(self):
        self.assertEqual(oracle.parse_output(encoded(('result', 'upgrade', 'returned'))), [('result', 'upgrade', 'returned')])
        with self.assertRaises(ValueError):
            oracle.parse_output('unframed runtime text\n')

    def test_pinned_probe_and_platform_before_any_process(self):
        with patch.object(oracle.subprocess, 'run', side_effect=AssertionError('no process')):
            with patch.object(oracle.platform, 'system', return_value='Linux'), self.assertRaises(ValueError):
                oracle.UpdateOracle(ROOT, mono_root=ROOT)
            with patch.object(oracle.platform, 'system', return_value='Darwin'), \
                    patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, 'ROOT'):
                oracle.UpdateOracle(ROOT)
            with patch.object(oracle.platform, 'system', return_value='Darwin'), self.assertRaises(ValueError):
                oracle.UpdateOracle(ROOT, mono_root=ROOT)  # runtime pins do not match the checkout


@unittest.skipUnless(os.environ.get('CBUS_FIRMWARE_ORACLE_BACKEND') == 'macos-mono' and platform.system() == 'Darwin'
                     and os.environ.get('CBUS_MONO_MACOS_ROOT') and os.environ.get('CBUS_FIRMWARE_UPDATER'),
                     'Set CBUS_FIRMWARE_ORACLE_BACKEND=macos-mono, CBUS_MONO_MACOS_ROOT and CBUS_FIRMWARE_UPDATER')
class OriginalUpdaterTests(unittest.TestCase):
    def test_selected_original_cases_match_update_plan(self):
        cases = [{'package': 'eDLTFirmware_1.7.0.zip', 'variant': 'TivaPCI', 'force': False},
                 {'package': 'eDLTFirmware_1.3.0.zip', 'variant': 'StellarisPCI', 'force': True},
                 {'package': 'eDLTFirmware_1.4.0.zip', 'variant': 'TivaNCC', 'force': False},
                 {'package': 'eDLTFirmware_1.7.0.zip', 'variant': 'StellarisPCI', 'force': True, 'fail_at': 3}]
        password = plans.read_password_file()[0]
        report = oracle.build_report(Path(os.environ['CBUS_FIRMWARE_UPDATER']).parent, password=password, cases=cases)
        self.assertEqual(report['status'], 'passed', [case['checks'] for case in report['cases']])
        self.assertEqual(report['cases'][1]['dfuprog'][1]['argv'], ['-z', '-c', '-l', '720896'])


if __name__ == '__main__':
    unittest.main()
