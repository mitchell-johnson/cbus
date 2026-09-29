"""Original updater step plan, private package reader and memory-peer execution.

Committed packages are synthetic (research/build_firmware_update_fixtures.py)
and encrypted with a synthetic test password. Expected argv sequences are the
literal FirmwareUpdater.UpgradeFirmware strings; the committed Mono receipt
separately records the unchanged original assembly producing them.
"""
import builtins
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from cbus_toolkit import firmware_update_plan as api
from cbus_toolkit.dfu_simulator import DFUSimulator

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / 'research/fixtures/firmware-update-packages'
RECEIPT = ROOT / 'research/fixtures/original-oracle-firmware-update-plan.json'
PASSWORD = b'cbus-synthetic-fixture'
HAS_PYZIPPER = importlib.util.find_spec('pyzipper') is not None
sys.path.insert(0, str(ROOT))
from research.build_firmware_update_fixtures import PACKAGES as FIXTURE_SPEC, image  # noqa: E402


def expected_images(package):
    return {name: image(name, size, address) for name, size, address in FIXTURE_SPEC[package][1]}


def argvs(plan):
    return [step['argv'] for step in plan['dfuprog_steps']]


def write_package(directory, name, entries):
    path = Path(directory, name)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for entry, data in entries:
            archive.writestr(entry, data)
    return path


class PlanTests(unittest.TestCase):
    def test_unforced_listed_version_skips_font_for_every_variant(self):
        package = PACKAGES / 'eDLTFirmware_1.7.0.zip'
        for variant, address, main in (('StellarisPCI', '0x2000', 'edlt_main_hwv1_1_7_0.bin'),
                                       ('TivaPCI', '0x4000', 'edlt_main_hwv2_1_7_0.bin'),
                                       ('TivaNCC', '0x4000', 'edlt_main_hwv3_1_7_0.bin')):
            plan = api.update_plan(package, variant=variant)
            self.assertTrue(plan['supported'], plan['issues'])
            self.assertEqual(argvs(plan), [['-m'], ['-b', '-a', address, '-r', '-f', f'<extracted:{main}>']])
            self.assertEqual([step['delay_before_ms'] for step in plan['dfuprog_steps']], [0, 10000])
            self.assertEqual(plan['dfuprog_steps'][-1]['native_arguments'], f'-b -a {address} -r -f "<extracted:{main}>"')
            self.assertFalse(plan['font_install']['performed'])
            self.assertEqual(plan['package']['extracted_entries'], [name for name, _, _ in FIXTURE_SPEC[package.name][1]])
            if variant == 'TivaNCC':
                self.assertEqual([step['serial_request'] for step in plan['post_check']['steps']],
                                 ['id\\r', 'nv\\r', 'nu\\r', 'nv\\r', 'rs\\r', 'id\\r'])
                self.assertIn("'1.7.0'", plan['post_check']['steps'][0]['check'])
            else:
                self.assertEqual(plan['post_check']['kind'], 'none')
        self.assertEqual(api.update_plan(package, variant='TivaPCI'), api.update_plan(package, variant='TivaPCI'))
        json.dumps(api.update_plan(package, variant='TivaNCC'))

    def test_forced_font_sequence_uses_literal_arguments_delays_and_failure_messages(self):
        plan = api.update_plan(PACKAGES / 'eDLTFirmware_1.7.0.zip', variant='TivaPCI', force_font=True)
        font = '<extracted:edlt_fontdata_1.0.0.bin>'
        self.assertEqual(argvs(plan), [['-m'], ['-z', '-c', '-l', '65536'], ['-z', '-b', '-a', '0', '-f', font], ['-m'],
                                       ['-b', '-a', '0x4000', '-r', '-f', '<extracted:edlt_main_hwv2_1_7_0.bin>']])
        self.assertEqual([step['delay_before_ms'] for step in plan['dfuprog_steps']], [0, 8000, 0, 0, 10000])
        self.assertEqual(plan['dfuprog_steps'][2]['native_arguments'], f'-z -b  -a 0 -f "{font}"')
        self.assertFalse(plan['dfuprog_steps'][2]['reset'])
        self.assertEqual([step['failure_message'].format(exit_code=7) for step in plan['dfuprog_steps']], [
            'Unable to prepare unit for firmware upgrade (exit code 7).',
            'Unable to clear flash memory for font data installation (exit code 7).',
            'Unable to write font data to unit (exit code 7).',
            'Unable to prepare unit for firmware upgrade (exit code 7).',
            'Unable to write firmware to unit (exit code 7).'])
        self.assertEqual(plan['font_erase'], {'formula': '(font_bytes / 65537 + 1) * 65536', 'font_bytes': 3000,
                                              'length': 65536, 'covers_font': True})
        self.assertTrue(plan['font_install']['forced'])

    def test_unlisted_version_installs_font_and_skips_unexpected_entries(self):
        plan = api.update_plan(PACKAGES / 'eDLTFirmware_1.8.0.zip', hardware_version='2 (tIvA)')
        self.assertEqual(plan['variant'], 'TivaPCI')
        self.assertTrue(plan['supported'], plan['issues'])
        self.assertTrue(plan['font_install']['performed'])
        self.assertFalse(plan['font_install']['package_version_in_font_data1_versions'])
        self.assertEqual(argvs(plan)[1], ['-z', '-c', '-l', '131072'])
        self.assertEqual(plan['package']['skipped_entries'], ['notes.txt'])
        self.assertNotIn('notes.txt', plan['package']['extracted_entries'])

    def test_missing_variant_image_matches_original_refusal_without_steps(self):
        for variant in ('TivaNCC',):
            plan = api.update_plan(PACKAGES / 'eDLTFirmware_1.5.0.zip', variant=variant)
            self.assertFalse(plan['supported'])
            self.assertEqual(plan['issues'], ['The selected firmware archive is not compatible with the connected eDLT unit.'])
            self.assertEqual(plan['dfuprog_steps'], [])

    def test_hardware_text_and_selector_validation(self):
        self.assertEqual(api.resolve_variant(hardware_version=''), 'StellarisPCI')
        self.assertEqual(api.resolve_variant(hardware_version='3.0 (Tiva + NCC)'), 'TivaNCC')
        with self.assertRaisesRegex(ValueError, 'Unit variant is unknown.'):
            api.resolve_variant(hardware_version='3.0 (tiva + ncc)')
        for kwargs in ({}, {'variant': 'TivaPCI', 'hardware_version': ''}, {'variant': 'Unknown'}):
            with self.assertRaises(ValueError):
                api.resolve_variant(**kwargs)
        with self.assertRaises(ValueError):
            api.update_plan(PACKAGES / 'eDLTFirmware_1.7.0.zip', variant='TivaPCI', force_font=1)

    def test_font_erase_formula_boundaries_include_native_under_coverage(self):
        for size, length in ((0, 65536), (65536, 65536), (65537, 131072), (131072, 131072), (131073, 131072),
                             (196608, 196608), (196609, 196608), (196610, 196608), (196611, 262144)):
            self.assertEqual(api.font_erase_length(size), length, size)
        for value in (-1, True, 1.0):
            with self.assertRaises(ValueError):
                api.font_erase_length(value)

    def test_package_shapes_the_original_refuses_or_cannot_describe(self):
        main, font = ('edlt_main_hwv1_x.bin', b'\0' * 64), ('edlt_fontdata_x.bin', b'\1' * 131073)
        with tempfile.TemporaryDirectory() as directory:
            short = write_package(directory, 'eDLTFirmware_1.8.0.zip', [main, font])
            plan = api.update_plan(short, variant='StellarisPCI')
            self.assertFalse(plan['supported'])
            self.assertEqual(plan['font_erase']['length'], 131072)
            self.assertIn('The original font erase length is shorter than the font data', plan['issues'])
            # The same bytes are admitted when the listed version skips the font.
            skipped = write_package(directory, 'eDLTFirmware_1.7.0.zip', [main, font])
            self.assertTrue(api.update_plan(skipped, variant='StellarisPCI')['supported'])
            self.assertFalse(api.update_plan(skipped, variant='StellarisPCI', force_font=True)['supported'])
            cases = {
                'directory': [main, font, ('folder/', b'')],
                'nested': [('sub/edlt_main_hwv1_x.bin', b'\0'), font],
                'duplicate': [main, ('edlt_main_hwv1_y.bin', b'\2'), font],
                'no-font': [main],
            }
            for name, entries in cases.items():
                plan = api.update_plan(write_package(directory, f'{name}_1.7.0.zip', entries), variant='StellarisPCI')
                self.assertFalse(plan['supported'], name)
            duplicate = api.update_plan(Path(directory, 'duplicate_1.7.0.zip'), variant='StellarisPCI')
            self.assertEqual(duplicate['selected_main_entry'], 'edlt_main_hwv1_y.bin')
            self.assertIn('last one', duplicate['issues'][0])
            self.assertEqual(api.update_plan(Path(directory, 'no-font_1.7.0.zip'), variant='StellarisPCI')['issues'],
                             ['The selected firmware archive is not compatible with the connected eDLT unit.'])


class PackageReaderTests(unittest.TestCase):
    def test_zipcrypto_entries_decrypt_in_memory_to_independent_expected_bytes(self):
        package = PACKAGES / 'eDLTFirmware_1.7.0.zip'
        self.assertEqual(api.read_package_entries(package, PASSWORD), expected_images(package.name))
        self.assertEqual(set(api.read_package_entries(package, PASSWORD, names={'edlt_fontdata_1.0.0.bin'})),
                         {'edlt_fontdata_1.0.0.bin'})
        with self.assertRaises(api.FirmwarePackageError) as caught:
            api.read_package_entries(package, b'wrong-password')
        self.assertNotIn('wrong-password', str(caught.exception))
        with self.assertRaises(api.FirmwarePackageError):
            api.read_package_entries(package, b'')

    @unittest.skipUnless(HAS_PYZIPPER, 'optional firmware extra (pyzipper) is not installed')
    def test_aes_entries_decrypt_with_optional_pyzipper(self):
        package = PACKAGES / 'eDLTFirmware_1.5.0.zip'
        self.assertEqual(api.read_package_entries(package, PASSWORD), expected_images(package.name))
        with self.assertRaises(api.FirmwarePackageError):
            api.read_package_entries(package, b'wrong-password')

    def test_aes_without_pyzipper_fails_clearly(self):
        real = builtins.__import__

        def blocked(name, *args, **kwargs):
            if name == 'pyzipper':
                raise ImportError('blocked for test')
            return real(name, *args, **kwargs)
        with patch('builtins.__import__', blocked):
            with self.assertRaisesRegex(api.FirmwarePackageError, 'optional firmware extra'):
                api.read_package_entries(PACKAGES / 'eDLTFirmware_1.5.0.zip', PASSWORD)
            # ZipCrypto remains readable with the standard library.
            self.assertEqual(len(api.read_package_entries(PACKAGES / 'eDLTFirmware_1.7.0.zip', PASSWORD)), 4)

    def test_password_file_and_environment_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, 'password')
            for content in (PASSWORD, PASSWORD + b'\n', PASSWORD + b'\r\n'):
                path.write_bytes(content)
                self.assertEqual(api.read_password_file(path), (PASSWORD, 'file'))
            with patch.dict(os.environ, {api.PASSWORD_FILE_ENV: str(path)}):
                self.assertEqual(api.read_password_file(), (PASSWORD, 'environment-file'))
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(api.read_password_file(), (None, None))
            for content in (b'', b'\n', b'x' * 4097):
                path.write_bytes(content)
                with self.assertRaises(api.FirmwarePackageError):
                    api.read_password_file(path)

    def test_image_inspection_reports_hashes_dfu_and_vector_facts_only(self):
        report = api.inspect_package_images(PACKAGES / 'eDLTFirmware_1.7.0.zip', PASSWORD)
        expected = expected_images('eDLTFirmware_1.7.0.zip')
        self.assertEqual({row['name']: row['sha256'] for row in report['images']},
                         {name: hashlib.sha256(data).hexdigest() for name, data in expected.items()})
        rows = {row['name']: row for row in report['images']}
        self.assertEqual(rows['edlt_fontdata_1.0.0.bin']['role'], 'Font')
        self.assertIsNone(rows['edlt_fontdata_1.0.0.bin']['cortex_m_vector_table'])
        table = rows['edlt_main_hwv3_1_7_0.bin']['cortex_m_vector_table']
        self.assertEqual((table['load_address'], table['reset_vector'], table['reset_handler_in_image']),
                         ('0x4000', '0x00004101', True))
        for row in report['images']:
            self.assertEqual((row['encryption'], row['native_download_path']), ('zipcrypto', 'raw binary at -a'))
            self.assertFalse(row['dfu_container']['valid'])
        self.assertFalse(report['authenticity_verified'])
        self.assertNotIn(PASSWORD.decode(), json.dumps(report))

    def test_image_facts_refuse_prefixed_or_misaddressed_main_images(self):
        # A Stellaris vector table in the Tiva slot places its reset handler below 0x4000.
        with tempfile.TemporaryDirectory() as directory:
            package = write_package(directory, 'eDLTFirmware_1.7.0.zip', [
                ('edlt_main_hwv2_x.bin', image('m', 64, 0x2000)), ('edlt_fontdata_x.bin', b'\1' * 64)])
            plan = api.update_plan(package, variant='TivaPCI')
            api.attach_image_inspection(plan, api.inspect_package_images(package, b'unused'))
            self.assertFalse(plan['supported'])
            self.assertIn('reset vector lies outside', plan['issues'][0])


class SimulatorTests(unittest.TestCase):
    def test_forced_plan_programs_font_and_main_through_fresh_host_sessions(self):
        package = PACKAGES / 'eDLTFirmware_1.7.0.zip'
        plan = api.update_plan(package, variant='TivaPCI', force_font=True)
        images = api.load_selected_images(package, plan, PASSWORD)
        self.assertEqual(sorted(images), ['edlt_fontdata_1.0.0.bin', 'edlt_main_hwv2_1_7_0.bin'])
        result = api.simulate_plan(plan, images)
        self.assertTrue(result['complete'])
        self.assertEqual([row.get('executed') for row in result['steps']], [False, True, True, False, True])
        self.assertTrue(all(row['outcome']['peer_verified'] for row in result['steps'] if row['executed']))
        self.assertEqual(result['steps'][1]['outcome']['length'], 65536)
        self.assertIn('not sent', result['steps'][4]['reset'])
        self.assertTrue(all(region['matches_image'] for region in result['regions'].values()))
        self.assertEqual(result['regions']['main-write']['sha256'],
                         hashlib.sha256(expected_images(package.name)['edlt_main_hwv2_1_7_0.bin']).hexdigest())
        self.assertTrue(result['development_evidence_only'])
        self.assertFalse(result['physical_device_verified'])

    def test_first_failed_step_stops_later_steps(self):
        package = PACKAGES / 'eDLTFirmware_1.8.0.zip'
        plan = api.update_plan(package, variant='StellarisPCI')
        images = api.load_selected_images(package, plan, PASSWORD)
        # External flash too small for the native 131072-byte font erase.
        result = api.simulate_plan(plan, images, external_size=65536)
        self.assertFalse(result['complete'])
        self.assertEqual(len(result['steps']), 2)
        self.assertFalse(result['steps'][-1]['executed'])
        self.assertEqual(result['regions'], {})
        with self.assertRaises(ValueError):
            api.simulate_plan(api.update_plan(PACKAGES / 'eDLTFirmware_1.5.0.zip', variant='TivaNCC'), images)
        with self.assertRaises(ValueError):
            api.simulate_plan(plan, {})

    def test_new_host_session_restarts_block_counter_and_preserves_flash(self):
        peer = DFUSimulator()
        peer.internal[8192:8196] = b'\0\1\2\3'
        peer.next_block, peer.state, peer.detached = 9, 10, True
        peer.new_host_session()
        self.assertEqual((peer.next_block, peer.state, peer.status, peer.detached, peer.host_sessions), (0, 2, 0, False, 1))
        self.assertEqual(bytes(peer.internal[8192:8196]), b'\0\1\2\3')


class CLITests(unittest.TestCase):
    def cli(self, *args, status=0, env=None):
        if env is None:
            env = {key: value for key, value in os.environ.items() if key != api.PASSWORD_FILE_ENV}
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', 'firmware', *map(str, args)],
                                capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        self.assertNotIn(PASSWORD.decode(), result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_plan_simulation_and_image_commands(self):
        package = PACKAGES / 'eDLTFirmware_1.7.0.zip'
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory, 'password')
            secret.write_bytes(PASSWORD + b'\n')
            plan = self.cli('update-plan', package, '--variant', 'StellarisPCI', '--force-font')
            self.assertEqual(len(plan['dfuprog_steps']), 5)
            self.assertNotIn('image_inspection', plan)
            inspected = self.cli('update-plan', package, '--hardware-version', '', '--package-password-file', secret)
            self.assertEqual(inspected['variant'], 'StellarisPCI')
            self.assertEqual(len(inspected['image_inspection']['images']), 4)
            refused = self.cli('update-plan', PACKAGES / 'eDLTFirmware_1.5.0.zip', '--variant', 'TivaNCC', status=1)
            self.assertFalse(refused['supported'])
            self.assertIn('requires', self.cli('update-simulate', package, '--variant', 'TivaPCI', status=1)['error'])
            env = dict(os.environ, **{api.PASSWORD_FILE_ENV: str(secret)})
            simulated = self.cli('update-simulate', package, '--variant', 'TivaPCI', '--force-font', env=env)
            self.assertTrue(simulated['complete'])
            self.assertEqual(simulated['plan']['variant'], 'TivaPCI')
            self.assertEqual(self.cli('inspect-images', package, '--package-password-file', secret)['password_source'], 'file')
            wrong = Path(directory, 'wrong')
            wrong.write_bytes(b'wrong-password')
            self.assertEqual(self.cli('inspect-images', package, '--package-password-file', wrong, status=1)['type'],
                             'FirmwarePackageError')
            self.assertEqual(sorted(path.name for path in Path(directory).iterdir()), ['password', 'wrong'])


class OriginalReceiptTests(unittest.TestCase):
    """Replays the committed original-assembly receipt against update-plan offline."""

    def test_receipt_argv_sequences_match_update_plan_for_same_shaped_packages(self):
        receipt = json.loads(RECEIPT.read_text())
        self.assertEqual(receipt['status'], 'passed')
        self.assertFalse(receipt['password_reported'] or receipt['plaintext_retained'] or receipt['physical_hardware_accessed'])
        probe = hashlib.sha256((ROOT / 'research/NativeFirmwareUpdateProbe.cs').read_bytes()).hexdigest()
        self.assertEqual(receipt['probe_sha256'], probe)
        self.assertEqual(len(receipt['cases']), 29)
        with tempfile.TemporaryDirectory() as directory:
            for case in receipt['cases']:
                self.assertTrue(all(case['checks'].values()), case)
                folder = Path(directory, f"{case['package']}-{case['variant']}-{case['force_font']}-{case['fail_at']}")
                folder.mkdir()
                entries = [(row['entry'], b'\0' * row['bytes']) for row in case['extracted'].values()]
                package = write_package(folder, case['package'], entries)
                plan = api.update_plan(package, variant=case['variant'], force_font=case['force_font'])
                observed = [row['argv'] for row in case['dfuprog']]
                expected = argvs(plan)[:case['fail_at']] if case['fail_at'] else argvs(plan)
                self.assertEqual(observed, expected, case['package'])
                self.assertEqual(plan['supported'], case['result'][0] != 'dowork')
                if case['fail_at']:
                    step = plan['dfuprog_steps'][case['fail_at'] - 1]
                    self.assertIn(step['failure_message'].format(exit_code=3), case['result'][1])


if __name__ == '__main__':
    unittest.main()
