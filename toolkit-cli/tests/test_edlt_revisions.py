"""KEYGL5 catalogue revisions: layout identity, original editor review, admission and native acceptance."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import cli
from cbus_toolkit.dlt_profiles import EDLT_DATABASE_REVISIONS, PROFILES, WORKFLOWS, admits, refusal
from cbus_toolkit.edlt_page_control import EdltPageControl
from test_macros import NATIVE, NATIVE_REASON, closed_network_project, native_endpoint
from tests.test_edlt import Session
from tests.test_edlt_page_control import fixture

ROOT = Path(__file__).resolve().parents[1]
FACTS = json.loads((ROOT / 'research/fixtures/dlt-profile-facts.json').read_text())
RECEIPT = ROOT / 'research/fixtures/edlt-revision-native-acceptance.json'
# Both boundaries of every admitted catalogue range; 5.5.00 is the prior evidence.
NATIVE_ADMITTED = ('1.6.00', '1.6.99', '1.7.00', '1.7.99', '5.4.00', '5.4.99', '5.5.00', '5.5.99')
NATIVE_REFUSED = (('1.5.01', '5055EDL', 'IsInternal'), ('1.5.99', '5055EDL', 'IsInternal'),
                  ('5.6.00', '5055EDL', 'IsInternal'), ('5.4.00', '5085EDL', 'only 5055EDL evidence'),
                  ('5.5.1', '5055EDL', 'canonical catalogue spelling'))
LIGHTING = ('--page', 1, '--position', 1, '--group', 42, '--mode', 'off-on', '--label-text', 'Revision Lamp',
            '--status-type', 'percent')
# Every original eDLT editor/model source file that reads a unit firmware
# value, from the pinned Toolkit 1.18.0.2754 decompilation. Each use is
# classified in docs/dlt-profiles.md; none selects a layout or widget.
EDITOR_FIRMWARE_FILES = frozenset((
    'CBusLogicModel/CBusLogicModel.Units.EDLT/EDLTUnit.cs', 'CBusLogicModel/CBusLogicModel.Units/CBusBaseGOC2.cs',
    'CBusLogicModel/CBusLogicModel.Units/CBusBaseModel.cs', 'CBusLogicModel/CBusLogicModel.Units/CBusBaseUnit.cs',
    'CBusLogicModel/CBusLogicModel.Units/CBusBaseUnitController.cs', 'EDLTCommon/EDLTCommon/EdltFirmware.cs',
    'eDLT/eDLT.Controls/TemplatesDialog.cs', 'eDLT/eDLT/FrmBaseUnit.cs'))


def schema_rows(document):
    """Every native PP INFO parameter definition without its unit-specific CurrentValue."""
    import xml.etree.ElementTree as ET
    rows = []
    for element in ET.fromstring(document).iter():
        if element.tag.rsplit('}', 1)[-1] == 'Param':
            rows.append({child.tag.rsplit('}', 1)[-1]: child.text or '' for child in element
                         if child.tag.rsplit('}', 1)[-1] != 'CurrentValue'})
    return rows


def portable(values):
    """Parameters with the per-fixture unit address removed (each revision is a distinct unit)."""
    return {name: value for name, value in values.items() if name != 'UnitAddress'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class RevisionFactsTests(unittest.TestCase):
    def test_admitted_ranges_are_exactly_the_public_catalogue_revisions(self):
        facts = FACTS['unit_types']['KEYGL5']
        public = [f"{row['min']}..{row['max']}" for row in facts['revisions'] if not row['internal']]
        self.assertEqual(list(EDLT_DATABASE_REVISIONS), public)
        # One specification and one C-Gate class for every revision and catalogue number.
        self.assertEqual((facts['spec_filenames'], facts['class_names']), (['KEYGL5.xml'], ['CBusEdlt']))
        spec = FACTS['specifications']['KEYGL5.xml']
        self.assertEqual((spec['includes'], spec['min_version'], spec['max_version']), ([], '0', '9'))
        self.assertEqual(spec['sha256'], PROFILES['KEYGL5'].spec_sha256)
        self.assertEqual({row[2] for row in WORKFLOWS['edlt-database-widgets'].admitted}, {'5055EDL'})

    def test_range_boundaries_gaps_and_internal_revisions(self):
        def reason(firmware, catalog='5055EDL'):
            return refusal('edlt-database-widgets', 'KEYGL5', firmware, catalog)
        for firmware in (*NATIVE_ADMITTED, '1.6.42', '1.7.03', '5.4.50', '5.5.01'):
            self.assertIsNone(reason(firmware), firmware)
        for firmware in ('1.5.01', '1.5.99', '5.6.00', '6.0.00', '9.0.00'):
            self.assertIn('IsInternal', reason(firmware), firmware)
        for firmware in ('1.5.00', '1.8.00', '2.0.00', '5.3.99', '9.0.01', '10.0.00'):
            self.assertIn('outside every C-Gate catalogue revision', reason(firmware), firmware)
        for firmware in ('01.06.00', '1.6.0', '5.5.1', '5.5.100'):
            self.assertIsNotNone(reason(firmware), firmware)
        for catalog in ('5085EDL', '5085EDLB', 'R5045EDL', 'R5045EDLW'):
            self.assertIn('only 5055EDL evidence', reason('1.6.00', catalog))

    def test_physical_parent_and_global_workflows_keep_550_only(self):
        for firmware in ('1.6.00', '1.7.99', '5.4.00', '5.5.99'):
            with self.subTest(firmware=firmware):
                for workflow in ('edlt-parent-metadata', 'edlt-global-source'):
                    self.assertIn(f'{workflow} evidence is retained only for 5.5.00',
                                  refusal(workflow, 'KEYGL5', firmware, '5055EDL'))
                self.assertIn('edlt-label-clear evidence is retained only for 5.5.00',
                              refusal('edlt-label-clear', 'KEYGL5', firmware))
                physical = '.'.join(f'{int(part):02d}' for part in firmware.split('.'))
                self.assertIn('edlt-physical-labels evidence is retained only for 5.5.00',
                              refusal('edlt-physical-labels', 'KEYGL5', physical))

    def test_physical_label_read_path_refuses_other_revisions_without_io(self):
        from cbus_toolkit.cmqtt import _supported_edlt, decode_edlt_labels
        self.assertTrue(_supported_edlt('KEYGL5', '05.05.00'))
        for firmware in ('01.06.00', '01.07.99', '05.04.00', '05.05.99'):
            self.assertFalse(_supported_edlt('KEYGL5', firmware), firmware)
        # The physical decoder stays pinned to the observed 5.5.00 configuration bytes.
        with self.assertRaisesRegex(ValueError, 'configuration version'):
            decode_edlt_labels(b'\x05\x04' + bytes(9214))


class RustExportTests(unittest.TestCase):
    def test_rust_admission_table_and_vectors_match_the_registry(self):
        result = subprocess.run([sys.executable, str(ROOT / 'research/export_dlt_admission.py'), '--check'],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        table = json.loads((ROOT.parent / 'rust/cbus-cgate/src/dlt_profiles.json').read_text())
        widgets = next(row for row in table['workflows'] if row['name'] == 'edlt-database-widgets')
        self.assertEqual([row[1] for row in widgets['admitted']], list(EDLT_DATABASE_REVISIONS))


class RevisionCLITests(unittest.TestCase):
    def invoke(self, args, status=0):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = cli.main(list(map(str, args)))
        self.assertEqual(code, status, output.getvalue() + error.getvalue())
        return json.loads(output.getvalue() or error.getvalue())

    def test_offline_export_identity_is_admitted_and_reported(self):
        spec = fixture(); editor = EdltPageControl(spec); values = Session(spec).values()
        with tempfile.TemporaryDirectory() as folder, patch.object(cli, '_edlt_page_control', return_value=editor), \
                patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('Offline must not connect')):
            path = Path(folder) / 'export.json'
            bare = Path(folder) / 'bare.json'; bare.write_text(json.dumps(values))
            self.assertEqual(self.invoke(('edlt', 'page-control-plan', bare, '--group', 7))['firmware'], '5.5.00')
            results = {}
            for firmware in NATIVE_ADMITTED:
                path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'KEYGL5',
                                            'firmware': firmware, 'catalog_number': '5055EDL',
                                            'parameters': values}))
                result = self.invoke(('edlt', 'page-control-plan', path, '--group', 7))
                self.assertEqual((result['unit_type'], result['firmware'], result['catalog_number']),
                                 ('KEYGL5', firmware, '5055EDL'))
                results[firmware] = {k: v for k, v in result.items() if k != 'firmware'}
            self.assertEqual(len({digest(row) for row in results.values()}), 1)
            for firmware, catalog, pattern in NATIVE_REFUSED:
                path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'KEYGL5',
                                            'firmware': firmware, 'catalog_number': catalog, 'parameters': values}))
                error = self.invoke(('edlt', 'page-control-plan', path, '--group', 7), status=1)['error']
                self.assertIn('identity differs', error); self.assertIn(pattern, error)

    def test_native_result_reports_the_verified_database_identity(self):
        self.assertEqual(cli._edlt_identity({'firmware': '5.5.00', 'x': 1}, ('KEYGL5', '1.6.00', '5055EDL')),
                         {'firmware': '1.6.00', 'x': 1})
        for identity in (None, object(), ('KEYGL5',)):
            self.assertEqual(cli._edlt_identity({'firmware': '5.5.00'}, identity), {'firmware': '5.5.00'})
        self.assertEqual(cli._edlt_identity([1], ('KEYGL5', '1.6.00', '5055EDL')), [1])


class NativeReceiptTests(unittest.TestCase):
    def test_retained_native_receipt_is_sanitized_and_complete(self):
        receipt = json.loads(RECEIPT.read_text())
        self.assertEqual(receipt['format'], 'cbus-edlt-revision-native-acceptance-v1')
        self.assertTrue(receipt['passed'])
        self.assertFalse(receipt['physical_hardware_verified'])
        self.assertEqual(receipt['spec_sha256'], PROFILES['KEYGL5'].spec_sha256)
        self.assertEqual([row['firmware'] for row in receipt['admitted']], list(NATIVE_ADMITTED))
        self.assertEqual([(row['firmware'], row['catalog_number']) for row in receipt['refused']],
                         [row[:2] for row in NATIVE_REFUSED])
        for field in ('schema_sha256', 'defaults_sha256', 'lighting_changes_sha256', 'page_control_changes_sha256',
                      'final_parameters_sha256'):
            self.assertEqual(len({row[field] for row in receipt['admitted']}), 1, field)
        for row in receipt['admitted']:
            self.assertTrue(row['identity_reported'] and row['saved_reloaded'] and row['label_bytes_verified'])
            self.assertTrue(row['preview_matches_offline_plan'])
            self.assertEqual(row['page_control_groups'], [0, 42, 254, 255])
        for row in receipt['refused']:
            self.assertTrue(row['values_unchanged'])
        text = RECEIPT.read_text()
        for forbidden in ('/Users/', '/Volumes/', 'DefaultValue', '<Param'):
            self.assertNotIn(forbidden, text)


VENDOR = os.environ.get('CBUS_DLT_VENDOR_ROOT')


@unittest.skipUnless(VENDOR, 'Set CBUS_DLT_VENDOR_ROOT to the owned Toolkit/C-Gate research vendor directory')
class OriginalEditorReviewTests(unittest.TestCase):
    """Re-check the reviewed firmware uses in the decompiled eDLT editor and C-Gate class."""

    def test_editor_firmware_reads_are_the_reviewed_non_layout_uses(self):
        root = Path(VENDOR) / 'edlt-decompiled'
        found = {path.relative_to(root).as_posix() for path in root.rglob('*.cs')
                 if 'FirmwareVersion' in path.read_text(errors='replace')}
        self.assertEqual(found, EDITOR_FIRMWARE_FILES)
        unit = (root / 'CBusLogicModel/CBusLogicModel.Units.EDLT/EDLTUnit.cs').read_text(errors='replace')
        # Database units report "n/a"; firmware reaches ConfigVersion only for network units or network saves.
        self.assertRegex(unit, r'if \(DatabaseUnit\)\s*\{\s*firmwareVersionUnit = "n/a";')
        self.assertEqual(len(re.findall(r'ConfigVersion = (?:FirmwareVersionUnit|text)\.Substring\(0, 3\)', unit)), 2)
        self.assertIn('if (!DatabaseUnit && !FirmwareVersionUnit.StartsWith(text))', unit)
        self.assertIn('if (DatabaseUnit && saveNw)', unit)
        form = (root / 'eDLT/eDLT/FrmBaseUnit.cs').read_text(errors='replace')
        self.assertEqual(len(re.findall(r'FirmwareVersionUnit', form)), 2)  # prompt and display binding
        # The specification arrives from C-Gate by catalogue-selected file name;
        # the editor never names a specification file or a version bound.
        for path in root.rglob('*.cs'):
            self.assertNotRegex(path.read_text(errors='replace'), r'KEYGL5\.xml|MinVersion|MaxVersion', path.name)

    def test_cgate_edlt_class_has_no_version_branch(self):
        root = Path(VENDOR) / 'cgate-decompiled/com/clipsal/cgate/cbus/dev'
        for path in root.glob('CBusEdlt*.java'):
            self.assertNotRegex(path.read_text(errors='replace').lower(), r'version|firmware|revision', path.name)

    def test_decoded_specification_has_one_unconditional_layout(self):
        text = (Path(VENDOR) / 'unitspec-plain/KEYGL5.xml').read_text(errors='replace')
        self.assertEqual(hashlib.sha256((Path(VENDOR) / 'unitspec-plain/KEYGL5.xml').read_bytes()).hexdigest(),
                         PROFILES['KEYGL5'].spec_sha256)
        self.assertEqual(len(re.findall(r'<MinVersion>', text)), 1)
        self.assertEqual(len(re.findall(r'<MaxVersion>', text)), 1)
        self.assertNotRegex(text, r'<Include|<Condition|<If\b|IncludeSpec')


@unittest.skipUnless(NATIVE, NATIVE_REASON)
class NativeRevisionTests(unittest.TestCase):
    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_database_workflow_is_identical_at_every_public_revision_boundary(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.edlt import EdltError
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer, xml_text
        from cbus_toolkit.unitspec import UnitSpecStore
        store = UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR'])
        editor = EdltPageControl(store.load('KEYGL5.xml'))
        report = {'format': 'cbus-edlt-revision-native-acceptance-v1',
                  'scope': ('KEYGL5 / 5055EDL database Lighting widget with static label text and Page Control '
                            'through owned native C-Gate 3.4.0.2001 on synthetic database units at each public '
                            'catalogue revision boundary; no physical unit, display, label transfer or network save'),
                  'spec_sha256': hashlib.sha256((store.directory / 'KEYGL5.xml').read_bytes()).hexdigest(),
                  'admitted': [], 'refused': [], 'passed': False, 'physical_hardware_verified': False}
        with native_endpoint() as (host, port), CGateClient(host, port=port, timeout=30) as client, \
                closed_network_project(client, 'RV') as project, tempfile.TemporaryDirectory() as folder:
            report['greeting'] = client.greeting
            network = f'//{project}/254'
            programmer, database = Programmer(client), NativeDatabase(client)
            finals = {}
            for index, firmware in enumerate(NATIVE_ADMITTED):
                with self.subTest(firmware=firmware):
                    address = 20 + index; source = f'/db{network}/p/{address}'
                    database.create_unit(network, address, f'Rev{address}', 'KEYGL5', firmware, catalog_number='5055EDL')
                    with programmer.load(network, source) as pp:
                        self.assertEqual((pp.unit_type, pp.firmware, pp.catalog_number), ('KEYGL5', firmware, '5055EDL'))
                        editor.common._verify_session(pp)
                        self.assertEqual(pp.verified_edlt_identity, ('KEYGL5', firmware, '5055EDL'))
                        schema = digest(schema_rows(xml_text(pp.info('*'))))
                        defaults = digest(portable(pp.values()))
                    args = ('cgate', '--host', host, '--port', port, '--timeout', 20, 'unit',
                            '--lock-address', network, '--source', source)
                    snapshot = Path(folder) / f'{address}.json'
                    exported = self.cli(*args, 'export', snapshot)
                    self.assertTrue(exported)
                    document = json.loads(snapshot.read_text())
                    self.assertEqual((document['unit_type'], document['firmware'], document['catalog_number']),
                                     ('KEYGL5', firmware, '5055EDL'))
                    plan = self.cli('edlt', 'lighting-plan', snapshot, *LIGHTING)
                    preview = self.cli(*args, '--dry-run', 'edlt-lighting', '--no-first-open', *LIGHTING)
                    self.assertFalse(preview['saved']); self.assertTrue(preview['verified'])
                    self.assertEqual((preview['changes'], preview['record_hex']), (plan['changes'], plan['record_hex']))
                    lighting = self.cli(*args, 'edlt-lighting', '--no-first-open', *LIGHTING)
                    self.assertTrue(lighting['saved'])
                    self.assertEqual((plan['firmware'], preview['firmware'], lighting['firmware']), (firmware,) * 3)
                    label = 'StaticTextString' + str(lighting['static_allocation']['index'])
                    encoded = bytes(int(value, 0) for value in lighting['parameters'][label].split())
                    self.assertEqual(encoded, b'Revision Lamp' + bytes(64 - len(b'Revision Lamp')))
                    groups, page_changes = [], []
                    for group in (0, 42, 254, 255):
                        result = self.cli(*args, 'edlt-page-control', '--no-first-open', '--group', group)
                        self.assertTrue(result['saved']); self.assertEqual(result['firmware'], firmware)
                        self.assertEqual(int(result['parameters']['KeySetsEnableGroup'], 0), group)
                        groups.append(group); page_changes.append(result['changes'])
                    final = self.cli(*args, 'show')
                    self.assertEqual(final, result['parameters'])
                    finals[source] = final
                    report['admitted'].append({
                        'firmware': firmware, 'catalog_number': '5055EDL', 'identity_reported': True,
                        'schema_sha256': schema, 'defaults_sha256': defaults,
                        'preview_matches_offline_plan': True,
                        'lighting_changes_sha256': digest(lighting['changes']), 'label_bytes_verified': True,
                        'page_control_groups': groups, 'page_control_changes_sha256': digest(page_changes),
                        'final_parameters_sha256': digest(portable(final))})
            for index, (firmware, catalog, pattern) in enumerate(NATIVE_REFUSED):
                with self.subTest(refused=firmware, catalog=catalog):
                    address = 40 + index; source = f'/db{network}/p/{address}'
                    database.create_unit(network, address, f'Ref{address}', 'KEYGL5', firmware, catalog_number=catalog)
                    with programmer.load(network, source) as pp:
                        before = pp.values()
                        with self.assertRaisesRegex(EdltError, pattern):
                            editor.configure(pp, group=42)
                        self.assertEqual(pp.values(), before)
                    args = ('cgate', '--host', host, '--port', port, '--timeout', 20, 'unit',
                            '--lock-address', network, '--source', source)
                    shown = self.cli(*args, 'show')
                    error = self.cli(*args, 'edlt-page-control', '--no-first-open', '--group', 42, status=1)
                    self.assertIn(pattern, error['error'])
                    self.assertEqual(self.cli(*args, 'show'), shown)
                    report['refused'].append({'firmware': firmware, 'catalog_number': catalog,
                                              'reason_matched': pattern, 'values_unchanged': True})
            for action in ('SAVE', 'CLOSE', 'LOAD', 'USE'):
                client.command(f'PROJECT {action} {project}')
            for source, values in finals.items():
                args = ('cgate', '--host', host, '--port', port, '--timeout', 20, 'unit',
                        '--lock-address', network, '--source', source)
                self.assertEqual(self.cli(*args, 'show'), values)
            for row in report['admitted']:
                row['saved_reloaded'] = True
            for field in ('schema_sha256', 'defaults_sha256', 'lighting_changes_sha256',
                          'page_control_changes_sha256', 'final_parameters_sha256'):
                self.assertEqual(len({row[field] for row in report['admitted']}), 1, field)
            report['passed'] = (len(report['admitted']) == len(NATIVE_ADMITTED)
                                and len(report['refused']) == len(NATIVE_REFUSED))
            self.assertTrue(report['passed'])
        if os.environ.get('CBUS_EDLT_REVISION_REPORT'):
            Path(os.environ['CBUS_EDLT_REVISION_REPORT']).write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main()
