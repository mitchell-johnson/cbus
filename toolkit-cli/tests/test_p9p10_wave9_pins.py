"""Offline P9/P10 wave-9 pins: preferences, firmware plan, NCC lifecycle.

Pure offline: no hardware, Windows registry, network, broker, or vendor
artifacts. Synthetic ZIPs and caller-supplied transcript bytes only.
Advances P9 #61 and P10 #64/#67 without touching ``rust/``,
commissioning, or the parity register:

* P9.02 (#61): ``ToolkitPreferencesStore.save`` skips every ``skip_save``
  preference, falls back from HKLM to HKCU on machine-write denial with an
  explicit ``write-preference-fallback`` row, and never claims real
  registry effects; the address preview is the fixed Level10 text.
* P10.01 (#64): the original updater plan has no version gate
  (downgrades/reinstalls proceed), aborts only on ``exit_code > 0``,
  keeps PCI success immediate while TivaNCC pins the six-step
  ``id/nv/nu/nv/rs/id`` serial post-check, and stays read-only.
* P10.01/P10.04 (#64/#67): the NCC restart write is unacknowledged with
  no final NCC version read, and the memory-peer simulation stops at the
  first failed step, sends no reset, executes no NCC post-check, and
  never claims hardware acceptance.
"""

from __future__ import annotations

import struct
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from cbus_toolkit import firmware_update_plan as plan_api
from cbus_toolkit.firmware_ncc import evaluate_ncc_post_check
from cbus_toolkit.toolkit_preferences_preview import render_address_preview
from cbus_toolkit.toolkit_preferences_store import (
    CGATE_KEY,
    DISPLAY_DEFINITIONS,
    DISPLAY_KEY,
    HKCU,
    HKLM,
    PREFERENCE_DEFINITIONS,
    TOOLKIT_KEY,
    RegistryValue,
    ToolkitPreferencesStore,
)

ID = (b'Manufacturer=Clipsal\r\nProduct=eDLT\r\nSerial Number=PRIVATE-SERIAL\r\n'
      b'HW Version=3.0 (Tiva + NCC)\r\nFW Version=1.7.0\r\n'
      b'CPU Speed=120\r\nUnit Address=20\r\n')
PROGRESS = b'Updating NCC Firmware..\r\nUpdate Started\r\nUpdate Complete\r\n'


def nv(current='1.0.0', embedded='1.1.0'):
    return (f'NCC current version: {current}\r\nNCC embedded version: {embedded}\r\n').encode()


def exchange(command, response=b'', outcome='response'):
    return {'command': command, 'response': response, 'outcome': outcome}


def synthetic_image(name, size, address=None):
    import hashlib

    seed = hashlib.sha256(name.encode()).digest()
    body = (seed * (size // len(seed) + 1))[:size]
    if address is None:
        return body
    return struct.pack('<II', 0x20008000, address + 0x101) + body[8:]


def write_package(directory, filename, entries):
    path = Path(directory) / filename
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_STORED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return path


def default_values():
    values = {}
    for spec in PREFERENCE_DEFINITIONS:
        if spec.kind == 'boolean':
            values[spec.name] = False
        elif spec.kind == 'integer':
            values[spec.name] = 0
        else:
            values[spec.name] = ''
    return values


class MemoryRegistry:
    """In-memory PreferenceRegistry; denies HKLM to pin the fallback path."""

    def __init__(self):
        self.writes = []

    def read_value(self, hive, key, name):
        raise FileNotFoundError(name)

    def write_value(self, hive, key, name, value):
        self.writes.append((hive, key, name))
        if hive == HKLM:
            raise OSError('machine key denied offline')
        return None

    def write_default_string(self, hive, key, value):
        return 0


class P9PreferencePins(unittest.TestCase):
    def test_save_skips_unsaved_falls_back_machine_write_without_effects(self):
        """P9.02: skipped prefs unwritten; HKLM denial falls back explicitly."""
        registry = MemoryRegistry()
        store = ToolkitPreferencesStore(registry)
        display = {name: False for name, _ in DISPLAY_DEFINITIONS}
        outcome = store.save(default_values(), display)
        self.assertTrue(outcome.complete)
        self.assertFalse(outcome.fully_observed)  # HKLM denial recorded
        written = {(hive, name) for hive, _, name in registry.writes}
        skipped = {spec.name for spec in PREFERENCE_DEFINITIONS if spec.skip_save}
        self.assertTrue(skipped)
        for name in skipped:
            self.assertFalse(any(row_name == name for _, row_name in written), name)
        # FeedbackLogSize is machine-first but saved: HKLM attempt + HKCU fallback.
        attempts = [(hive, name) for hive, _, name in registry.writes
                    if name == 'FeedbackLogSize']
        self.assertIn((HKLM, 'FeedbackLogSize'), attempts)
        self.assertIn((HKCU, 'FeedbackLogSize'), attempts)
        actions = [row['action'] for row in outcome.as_dict()['operations']
                   if row.get('name') == 'FeedbackLogSize']
        self.assertIn('write-preference-fallback', actions)
        evidence = outcome.as_dict()
        self.assertFalse(evidence['transactional'])
        self.assertFalse(evidence['runtime_effects_applied'])
        self.assertFalse(evidence['actual_registry_backend_verified'])

    def test_address_preview_is_fixed_level10_text(self):
        """P9.02: preview pins the four original flag combinations."""
        self.assertEqual(render_address_preview(tag_hex=False, tag_override=False), 'Level 10')
        self.assertEqual(render_address_preview(tag_hex=True, tag_override=False), 'Level 10')
        self.assertEqual(render_address_preview(tag_hex=False, tag_override=True), '010 - Level 10')
        self.assertEqual(render_address_preview(tag_hex=True, tag_override=True), '010 (0Ah) - Level 10')
        with self.assertRaises(ValueError):
            render_address_preview(tag_hex=1, tag_override=True)


class P10PlanPins(unittest.TestCase):
    def test_plan_has_no_version_gate_and_pins_variant_post_checks(self):
        """P10.01: no gate, exit-code abort, PCI none vs NCC six-step check."""
        with TemporaryDirectory() as directory:
            pci_package = write_package(
                directory, 'eDLTFirmware_1.7.0.zip',
                [('edlt_main_hwv2_1_7_0.bin', synthetic_image('m', 128, 0x4000)),
                 ('edlt_fontdata_1.0.0.bin', synthetic_image('f', 64))])
            pci_package = Path(directory) / 'pci' / 'eDLTFirmware_1.7.0.zip'
            pci_package.parent.mkdir()
            pci_package.write_bytes(Path(directory, 'eDLTFirmware_1.7.0.zip').read_bytes())
            plan = plan_api.update_plan(pci_package, variant='TivaPCI')
            self.assertTrue(plan['supported'], plan['issues'])
            self.assertEqual(plan['version_gate'], 'none')
            self.assertIn('exit_code > 0', plan['abort_rule'])
            self.assertTrue(any('downgrade' in quirk for quirk in plan['native_quirks']))
            self.assertEqual(plan['post_check']['kind'], 'none')
            self.assertEqual(plan['dfuprog_steps'][-1]['argv'][2], '0x4000')
            self.assertTrue(plan['read_only'])
            self.assertFalse(plan['firmware_written'])
            self.assertFalse(plan['image_contents_verified'])

            ncc_dir = Path(directory) / 'ncc'
            ncc_dir.mkdir()
            ncc_package = write_package(
                ncc_dir, 'eDLTFirmware_1.7.0.zip',
                [('edlt_main_hwv3_1_7_0.bin', synthetic_image('m3', 128, 0x4000)),
                 ('edlt_fontdata_1.0.0.bin', synthetic_image('f', 64))])
            ncc_plan = plan_api.update_plan(ncc_package, variant='TivaNCC')
            self.assertTrue(ncc_plan['supported'], ncc_plan['issues'])
            self.assertEqual(ncc_plan['post_check']['kind'], 'ncc-serial')
            self.assertEqual([step['serial_request'] for step in ncc_plan['post_check']['steps']],
                             ['id\\r', 'nv\\r', 'nu\\r', 'nv\\r', 'rs\\r', 'id\\r'])


class P10NCCLifecyclePins(unittest.TestCase):
    def test_restart_gap_and_failed_simulation_stop_without_hardware(self):
        """P10.01/P10.04: restart unacked without final read; sim stops early."""
        rows = [exchange('id', ID), exchange('nv', nv('1.0.0', '1.1.0')),
                exchange('nu', PROGRESS), exchange('nv', nv('0.0.0', '1.1.0')),
                exchange('rs', outcome='write-ok'),
                exchange('id', ID)]
        result = evaluate_ncc_post_check('1.7.0', rows)
        self.assertTrue(result['native_success'])
        restart_step = next(step for step in result['steps'] if step['step'] == 'restart')
        self.assertFalse(restart_step['acknowledged'])
        self.assertIn('restart:no-final-ncc-version-read-in-original',
                      result['verification_gaps'])
        self.assertFalse(result['transcript_checks_passed'])
        for field in ('hardware_accessed', 'native_execution', 'physical_acceptance',
                      'destructive_execution_supported', 'raw_responses_reported'):
            self.assertFalse(result[field])
        self.assertEqual(result['commands_sent'], 0)

        with TemporaryDirectory() as directory:
            package = write_package(
                directory, 'eDLTFirmware_1.8.0.zip',
                [('edlt_main_hwv2_1_8_0.bin', synthetic_image('m', 128, 0x4000)),
                 ('edlt_fontdata_1.8.0.bin', synthetic_image('f', 70000))])
            sim_plan = plan_api.update_plan(package, variant='TivaPCI')
            self.assertTrue(sim_plan['supported'], sim_plan['issues'])
            self.assertTrue(sim_plan['font_install']['performed'])
            images = plan_api.load_selected_images(package, sim_plan, b'offline-pin-password')
            simulated = plan_api.simulate_plan(sim_plan, images, external_size=65536)
            self.assertFalse(simulated['complete'])
            self.assertEqual(simulated['regions'], {})
            self.assertFalse(simulated['steps'][0]['executed'])
            self.assertIn('no-op', simulated['steps'][0]['simulated'])
            self.assertTrue(simulated['development_evidence_only'])
            self.assertFalse(simulated['physical_device_verified'])
            self.assertIn('NCC serial path', simulated['post_check'])


if __name__ == '__main__':
    unittest.main()
