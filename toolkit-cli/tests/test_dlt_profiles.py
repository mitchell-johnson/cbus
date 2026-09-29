"""DLT/eDLT profile registry: sanitized facts, admission, refusals and routed gates."""
import itertools
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest

from cbus_toolkit import dlt_profiles as registry
from cbus_toolkit.dlt_profiles import (
    HELP_ONLY_CATALOG_NAMES, PROFILES, WORKFLOWS, DltProfileError, admits, admitted_types, lookup,
    physical_firmware, refusal, require)

ROOT = Path(__file__).resolve().parents[1]
FACTS = json.loads((ROOT / 'research/fixtures/dlt-profile-facts.json').read_text())
FIRMWARE = json.loads((ROOT / 'research/fixtures/edlt-firmware-package-facts.json').read_text())
EDLT = ('KEYGL5', '5.5.00', '5055EDL')
EDLT_WORKFLOWS = ('edlt-database-widgets', 'edlt-parent-metadata', 'edlt-global-source')


class FactsTests(unittest.TestCase):
    def test_profiles_match_the_sanitized_catalogue_spec_and_help_receipt(self):
        self.assertEqual(set(PROFILES), set(FACTS['unit_types']))
        for unit_type, profile in PROFILES.items():
            facts = FACTS['unit_types'][unit_type]
            with self.subTest(unit_type=unit_type):
                self.assertEqual(list(profile.catalog_numbers), facts['catalog_numbers'])
                self.assertEqual([row.as_dict() for row in profile.revisions], facts['revisions'])
                self.assertEqual([profile.spec_filename], facts['spec_filenames'])
                self.assertEqual(profile.spec_sha256, FACTS['specifications'][profile.spec_filename]['sha256'])
                topics = {row['topic_id'] for row in FACTS['help_topics'] if unit_type in row['unit_types']}
                self.assertLessEqual(set(profile.help_topics), topics)
                named = {name for row in FACTS['help_topics'] if row['topic_id'] in profile.help_topics
                         for name in row['catalog_names']}
                self.assertEqual(set(profile.help_catalog_names), named)
                if profile.label_spec:
                    self.assertEqual(FACTS['specifications'][profile.spec_filename]['includes'], [profile.label_spec])
        self.assertEqual(registry.I_DLT_SHA256, FACTS['specifications']['I_DLT.xml']['sha256'])
        self.assertEqual(registry.I_DLT_MIN_VERSION, FACTS['specifications']['I_DLT.xml']['min_version'])
        self.assertEqual(registry.I_DLTF_SHA256, FACTS['specifications']['I_DLTF.xml']['sha256'])
        self.assertFalse(FACTS['specifications']['I_DLTF.xml']['included_by_any_spec'])
        self.assertEqual(FACTS['specifications']['KEYL5.xml']['type'], 'KEYL5')

    def test_catalogue_alias_finding(self):
        findings = FACTS['catalogue_alias_findings']
        self.assertEqual(sorted(HELP_ONLY_CATALOG_NAMES), findings['help_catalog_names_not_in_catalogue'])
        self.assertEqual(findings['keygl5_help_catalog_names'], sorted(PROFILES['KEYGL5'].help_catalog_names))
        self.assertFalse(findings['help_names_5055EDL'])
        self.assertEqual(findings['help_topic_20074_unit_types'], ['KEYH5'])
        self.assertFalse(findings['catalogue_has_KEYH5'])
        self.assertNotIn('KEYH5', FACTS['unit_types'])

    def test_receipts_retain_no_vendor_text_or_paths(self):
        for name in ('dlt-profile-facts.json', 'edlt-firmware-package-facts.json'):
            text = (ROOT / 'research/fixtures' / name).read_text()
            for forbidden in ('/Users/', '/Volumes/', '"password', 'Description', 'DefaultValue', '<Param'):
                self.assertNotIn(forbidden, text, name)


class FirmwarePackageFactsTests(unittest.TestCase):
    def test_central_directory_inventory_agrees_with_the_updater_research(self):
        research = json.loads((ROOT / 'docs/firmware-research.json').read_text())
        self.assertEqual(FIRMWARE['format'], 'cbus-edlt-firmware-package-facts-v1')
        self.assertIn('no entry opened, decompressed or decrypted', FIRMWARE['method'])
        self.assertEqual(FIRMWARE['cbus_firmware_mapping']['status'], 'unmapped')
        self.assertEqual([row['name'] for row in FIRMWARE['packages']], [row['name'] for row in research['packages']])
        for package, prior in zip(FIRMWARE['packages'], research['packages']):
            with self.subTest(package=package['name']):
                self.assertEqual(package['sha256'], prior['sha256'])
                self.assertEqual(package['package_version'], package['name'][len('eDLTFirmware_'):-4])
                self.assertEqual([(e['name'], e['uncompressed_bytes'], e['crc32']) for e in package['entries']],
                                 [(e['name'], e['bytes'], e['crc32']) for e in prior['entries']])
                self.assertTrue(all(entry['encrypted'] for entry in package['entries']))
                offsets = [entry['local_header_offset'] for entry in package['entries']]
                self.assertEqual(offsets, sorted(offsets))
                self.assertEqual(offsets[0], 0)
                self.assertLess(sum(entry['compressed_bytes'] for entry in package['entries']), package['bytes'])

    def test_encryption_schemes_are_recorded_per_package(self):
        schemes = {row['package_version']: {entry['encryption'] for entry in row['entries']}
                   for row in FIRMWARE['packages']}
        self.assertEqual(schemes, {'1.3.0': {'winzip-aes-256 (AE-2)'}, '1.4.0': {'winzip-aes-256 (AE-2)'},
                                   '1.5.0': {'winzip-aes-256 (AE-2)'}, '1.7.0': {'pkware-traditional'}})
        for package in FIRMWARE['packages']:
            for entry in package['entries']:
                if entry['aes_extra']:
                    # AE-2 stores no CRC; the real method is carried in the 0x9901 extra field.
                    self.assertEqual((entry['compression_method'], entry['crc32']), (99, '00000000'))
                    self.assertEqual(entry['aes_extra']['actual_compression_method'], 8)
                else:
                    self.assertEqual(entry['compression_method'], 8)
        variants = {row['package_version']: sorted(re.findall(r'hwv[0-9]', ' '.join(e['name'] for e in row['entries'])))
                    for row in FIRMWARE['packages']}
        self.assertEqual(variants['1.7.0'], ['hwv1', 'hwv2', 'hwv3'])
        self.assertEqual(variants['1.5.0'], ['hwv1', 'hwv2'])


class AdmissionTests(unittest.TestCase):
    def test_keygl5_550_evidence_is_admitted_everywhere_it_was_before(self):
        for workflow in EDLT_WORKFLOWS:
            self.assertIsNone(refusal(workflow, *EDLT), workflow)
        self.assertIsNone(refusal('edlt-label-clear', 'KEYGL5', '5.5.00'))
        self.assertIsNone(refusal('edlt-physical-labels', 'KEYGL5', '05.05.00'))
        self.assertIsNone(refusal('serial-population', 'KEYGL5'))
        self.assertEqual(admitted_types('serial-population'), {'KEYGL5'})

    def test_physical_firmware_matches_the_retired_regex_exactly(self):
        retired = re.compile(r'0?5\.0?5\.0{1,2}')
        digits = ['', '0', '5', '00', '05', '50', '000', '005', '1', '4']
        for parts in itertools.product(digits, repeat=3):
            text = '.'.join(parts)
            with self.subTest(firmware=text):
                self.assertEqual(admits('edlt-physical-labels', 'KEYGL5', text), retired.fullmatch(text) is not None)
        self.assertEqual(physical_firmware('05.05.00'), '5.5.00')
        self.assertIsNone(physical_firmware(None))

    def test_database_firmware_and_catalogue_are_exact(self):
        for firmware in ('5.5.0', '05.05.00', '5.5.01', '5.4.00', '1.7.00', '5.6.00'):
            self.assertIsNotNone(refusal('edlt-database-widgets', 'KEYGL5', firmware, '5055EDL'), firmware)
            self.assertIsNotNone(refusal('edlt-label-clear', 'KEYGL5', firmware), firmware)
        for catalog in ('5085EDL', '5085EDLB', 'R5045EDL', 'R5045EDLW', '5505ED', '5085ED', 'R5045ED', None, 'X'):
            self.assertIsNotNone(refusal('edlt-database-widgets', 'KEYGL5', '5.5.00', catalog), catalog)

    def test_explicit_refusal_reasons(self):
        cases = (
            (('edlt-database-widgets', 'KEYGL5', '5.4.00', '5055EDL'), 'not extrapolated'),
            (('edlt-physical-labels', 'KEYGL5', '1.7.03'), '1.7.00..1.7.99'),
            (('edlt-database-widgets', 'KEYGL5', '10.0.00', '5055EDL'), 'outside every C-Gate catalogue'),
            (('edlt-database-widgets', 'KEYGL5', '5.5.00', '5085EDL'), 'only 5055EDL evidence'),
            (('edlt-database-widgets', 'KEYGL5', '5.5.00', '5505ED'), 'help catalogue name'),
            (('edlt-database-widgets', 'KEYBL5', '2.1.00', '5085DL'), 'classic Saturn'),
            (('edlt-physical-labels', 'KEYDL4', '3.0.00'), 'classic Decorator'),
            (('serial-population', 'KEYML5'), 'no retained evidence'),
            (('classic-dlt-label-variants', 'KEYGL5', '5.5.00', '5055EDL'), 'LabelFlavour'),
            (('classic-dlt-label-variants', 'KEYBL5', '1.4.00', '5085DL'), 'MinVersion 2.0'),
            (('classic-dlt-label-variants', 'KEYDL4', '2.0.00', 'E5084DL'), 'IsInternal'),
            (('classic-dlt-label-variants', 'KEYDL4', '3.0.00', '5084DL'), 'help catalogue name'),
            (('classic-dlt-label-variants', 'KEYML5', '3.0.00', 'SLC5055DL'), 'help catalogue name'),
            (('classic-dlt-label-variants', 'KEYH5', '5.5.00'), 'topic 20074'),
            (('classic-dlt-label-variants', 'KEYL5', '2.1.00'), 'KEYBL5'),
            (('edlt-database-widgets', 'KEY5', '1.0', None), 'not a DLT'),
            (('edlt-database-widgets', 'KEYGL5', 'bad', '5055EDL'), 'recognised version'),
            (('edlt-database-widgets', ['KEYGL5'], '5.5.00', '5055EDL'), 'must be text'),
            (('edlt-database-widgets', 'KEYGL5', '5.5.00', ['5055EDL']), 'must be text'),
            (('edlt-database-widgets', 'KEYGL5', 5.5, '5055EDL'), 'recognised version'),
        )
        for args, pattern in cases:
            with self.subTest(args=args):
                self.assertIn(pattern, refusal(*args))
        with self.assertRaisesRegex(DltProfileError, 'Unknown DLT workflow'):
            refusal('bogus', *EDLT)
        with self.assertRaisesRegex(ValueError, '^prefix: KEYGL5 firmware 5.4.00'):
            require('edlt-label-clear', 'KEYGL5', '5.4.00', error=ValueError, message='prefix')

    def test_classic_admission_covers_public_revisions_from_i_dlt_min_version(self):
        admitted = {(unit_type, firmware) for unit_type in ('KEYBL5', 'KEYML5', 'KEYDL4')
                    for firmware in ('1.1', '1.4.00', '1.4.08', '2.0.00', '2.0.50', '2.1.00', '2.4.00', '3.0.00',
                                     '3.0.57', '3.0.99', '3.1.00')
                    if admits('classic-dlt-label-variants', unit_type, firmware)}
        expected = {(t, f) for t in ('KEYBL5', 'KEYML5') for f in ('2.0.00', '2.1.00', '3.0.00', '3.0.57', '3.0.99')}
        expected |= {('KEYDL4', f) for f in ('2.1.00', '3.0.00', '3.0.57', '3.0.99')}
        self.assertEqual(admitted, expected)

    def test_capability_flags_and_lookup(self):
        self.assertTrue(PROFILES['KEYGL5'].static_label_text and PROFILES['KEYGL5'].edlt_widgets)
        for unit_type in ('KEYBL5', 'KEYML5', 'KEYDL4'):
            profile = PROFILES[unit_type]
            self.assertFalse(profile.static_label_text or profile.edlt_widgets)
            self.assertTrue(profile.label_variant_selection and profile.dynamic_labels)
        view = lookup('KEYGL5', '05.05.00')
        self.assertEqual(view['catalogue_revision']['min'], '5.5.00')
        self.assertTrue(view['workflows']['edlt-physical-labels']['admitted'])
        self.assertFalse(view['workflows']['edlt-database-widgets']['admitted'])
        self.assertIsNone(lookup('KEYH5')['profile'])
        document = registry.registry()
        self.assertEqual(set(document['workflows']), set(WORKFLOWS))
        self.assertIn('I_DLTF.xml', document['findings']['unused_fragments'])


class RoutedGateTests(unittest.TestCase):
    def test_cmqtt_physical_gate_and_inventory_kind(self):
        from types import SimpleNamespace
        from cbus_toolkit.cmqtt import _record_kind, _supported_edlt
        self.assertTrue(_supported_edlt('KEYGL5', '05.05.00'))
        self.assertFalse(_supported_edlt('KEYGL5', '5.4.00'))
        self.assertFalse(_supported_edlt('KEYBL5', '2.1.00'))
        base = dict(presence='single', status='ok', errors=(), state='ok')
        kinds = [_record_kind(SimpleNamespace(**base, unit_type=t, firmware=f))
                 for t, f in (('KEYGL5', '5.5.00'), ('KEYGL5', '5.4.00'), ('KEYBL5', '2.1.00'))]
        self.assertEqual(kinds, ['supported', 'unsupported', 'other'])

    def test_database_and_export_gates_carry_registry_reasons(self):
        from cbus_toolkit.edlt import EdltError, EdltLighting
        from cbus_toolkit.edlt_global_cli import read_parameters
        from cbus_toolkit.serial_population import _SUPPORTED_TYPES
        from cbus_toolkit.unitspec import UnitSpec
        spec = UnitSpec('KEYGL5.xml', {'Type': 'KEYGL5'}, (), {})
        with self.assertRaisesRegex(EdltError, 'only 5055EDL evidence'):
            EdltLighting(spec, catalog_number='R5045EDL')
        with self.assertRaisesRegex(EdltError, 'not extrapolated'):
            EdltLighting(spec, firmware='5.4.00')
        with self.assertRaisesRegex(EdltError, 'not KEYGL5.xml'):
            EdltLighting(UnitSpec('OTHER.xml', {'Type': 'KEYGL5'}, (), {}))
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source.json'
            path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'KEYGL5',
                                        'firmware': '5.5.00', 'catalog_number': '5085EDL', 'parameters': {}}))
            with self.assertRaisesRegex(ValueError, 'differs from KEYGL5 / 5055EDL / 5.5.00: Catalogue'):
                read_parameters(path)
        self.assertEqual(_SUPPORTED_TYPES, {'KEYE1', 'KEYGL5', 'PC_CNIED'})

    def test_scattered_literal_gates_are_retired(self):
        source = ROOT / 'src/cbus_toolkit'
        for name in ('cmqtt.py', 'edlt_label_clear.py', 'edlt_parent_metadata.py', 'edlt_global_cli.py',
                     'serial_population.py'):
            text = (source / name).read_text()
            self.assertNotIn("!= '5.5.00'", text, name)
            self.assertNotIn("('KEYGL5', '5.5.00', '5055EDL')", text, name)
        self.assertNotIn('_EDLT_FIRMWARE', (source / 'cmqtt.py').read_text())
        self.assertFalse((source / 'dlt_variant_guard.py').exists())


VENDOR = os.environ.get('CBUS_DLT_VENDOR_ROOT')


@unittest.skipUnless(VENDOR, 'Set CBUS_DLT_VENDOR_ROOT to the owned Toolkit/C-Gate research vendor directory')
class VendorDerivationTests(unittest.TestCase):
    def test_receipts_match_a_fresh_derivation(self):
        root = Path(VENDOR)
        result = subprocess.run(
            [sys.executable, str(ROOT / 'research/dlt_profile_facts.py'), '--check',
             '--catalogue', str(root / 'cgate/app/unitspec/cbusunits.xml'), '--spec-dir', str(root / 'unitspec-plain'),
             '--help-dir', str(root / 'toolkit-help'), '--toolkit-exe', str(root / 'toolkit/app/CBusToolkit.exe'),
             '--firmware-dir', str(root / 'toolkit/app/Firmware/eDLTFirmware')],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
