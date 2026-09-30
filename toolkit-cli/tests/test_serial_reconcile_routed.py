"""Offline routed reconciliation: literal-wire peers and synthetic XML/CBZ only."""
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from cbus_toolkit import cli
from cbus_toolkit.pci_selected_serial import SelectedSerialPlan, route_from_project
from cbus_toolkit.project import ProjectDocument
from cbus_toolkit.serial_reconcile import (ProjectFileDatabase, ReconcileError, ReconcileRecord,
                                          default_record_path, reconcile, verify_journal)
from tests.test_commissioning_route import line
from tests.test_pci_selected_serial_routed import (A, ONE, SIX, after_responses, before_responses,
                                                 manager, peer, receipt)

OID = '7c0e0f10-1111-4222-8333-944455556601'
KEEPER = '7c0e0f10-1111-4222-8333-944455556602'


def unit(oid, address, serial, unit_type='KEYE1'):
    return (f'<Unit><OID>{oid}</OID><TagName>Synthetic</TagName><Address>{address}</Address>'
            f'<UnitType>{unit_type}</UnitType><SerialNumber>{serial}</SerialNumber>'
            '<FirmwareVersion>2.5.00</FirmwareVersion><Description>Keep A &amp; B</Description>'
            '<vendor:Opaque xmlns:vendor="urn:synthetic">kept</vendor:Opaque>'
            f'<PP Name="UnitAddress" Value="{hex(address)}"/>'
            '<PP Name="GroupAddress" Value="0x1 0xff"/></Unit>')


def project_bytes(depth, unit_type='KEYE1'):
    text = line(depth)[0].decode()
    # Duplicate serial on another network must not make the target ambiguous.
    text = text.replace('</Network>', unit(KEEPER, 20, A) + '</Network>', 1)
    ending = '</Network></Project></Installation>'
    target = unit(OID, 255, A, unit_type)
    target += f'<Unit><Address>21</Address><UnitType>KEYE1</UnitType><Partner>{OID}</Partner></Unit>'
    return text.replace(ending, target + ending).encode()


class RoutedReconcileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def completed(self, depth=1, cbz=False, exchange=None, unit_type='KEYE1', transform=None):
        route = ONE if depth == 1 else SIX
        project = self.dir / ('project.cbz' if cbz else 'project.xml')
        raw = project_bytes(depth, unit_type)
        if transform is not None:
            raw = transform(raw)
        if cbz:
            with ZipFile(project, 'w') as archive:
                archive.writestr('project.xml', raw)
                archive.writestr('attachments/opaque.bin', b'\x00opaque\xff')
        else:
            project.write_bytes(raw)
        derived, digest = route_from_project(project, source_network=254, target_network=254-depth)
        self.assertEqual(derived, route)
        with peer(before_responses(route)) as (endpoint, _):
            plan = manager(endpoint).plan(A, 6, route=route, project_sha256=digest)
        journal = self.dir / 'journal.json'
        responses = before_responses(route) + [exchange if exchange is not None else b'g.' + receipt(route, 6, A)]
        with peer(responses + after_responses(route)) as (endpoint, _):
            value = plan.as_dict(); value['endpoint'] = dict(host=endpoint[0], port=endpoint[1])
            value['before'] = dict(value['before'], endpoint=value['endpoint'])
            result = manager(endpoint).apply(SelectedSerialPlan.from_dict(value), recovery_path=journal,
                project=project, source_network=254, target_network=254-depth)
        self.assertEqual(result.outcome, 'observed_expected_change')
        return project, journal, project.read_bytes()

    def assert_preserved(self, project, before, depth):
        document = ProjectDocument.load(project)
        target = f'/network/{254-depth}/unit/6'
        self.assertEqual(document.path_of(document.resolve('oid:' + OID)), target)
        self.assertEqual(document.parameters(target), {'UnitAddress': '0x6', 'GroupAddress': '0x1 0xff'})
        self.assertEqual(document.get_field(f'/network/{254-depth}/unit/21', 'Partner'), OID)
        document.update(target, {'Address': '255'})
        document.set_parameter(f'/network/{254-depth}/unit/255', 'UnitAddress', '0xff')
        self.assertEqual(document.raw_xml(), ProjectDocument.from_snapshot(before).raw_xml())
        if project.suffix == '.cbz':
            with ZipFile(project) as archive:
                self.assertEqual(archive.read('attachments/opaque.bin'), b'\x00opaque\xff')

    def test_one_and_six_bridge_xml_and_cbz_scope_and_preservation(self):
        for depth in (1, 6):
            for cbz in (False, True):
                with self.subTest(depth=depth, cbz=cbz), tempfile.TemporaryDirectory() as directory:
                    self.dir = Path(directory)
                    project, journal, before = self.completed(depth, cbz)
                    planned = reconcile(journal, ProjectFileDatabase(project))
                    self.assertEqual(planned['outcome'], 'planned')
                    self.assertEqual(planned['unit']['network'], 254-depth)
                    self.assertEqual(project.read_bytes(), before)
                    self.assertFalse(default_record_path(journal).exists())
                    result = reconcile(journal, ProjectFileDatabase(project), apply=True, network=254-depth)
                    self.assertEqual(result['outcome'], 'reconciled')
                    self.assertFalse(result['bus_io_performed'])
                    self.assert_preserved(project, before, depth)
                    saved = project.read_bytes()
                    with patch.object(ProjectDocument, 'save', side_effect=AssertionError('db_done wrote')):
                        self.assertEqual(reconcile(journal, ProjectFileDatabase(project), apply=True)['outcome'],
                                         'already_reconciled')
                    self.assertEqual(project.read_bytes(), saved)

    def test_fresh_exact_inventory_admits_lost_and_wrong_route_receipt(self):
        for exchange in (b'g.', b'g.' + receipt([252], 6, A)):
            with self.subTest(exchange=exchange), tempfile.TemporaryDirectory() as directory:
                self.dir = Path(directory)
                project, journal, _ = self.completed(exchange=exchange)
                self.assertFalse(verify_journal(journal).receipt_matches_request)
                self.assertEqual(reconcile(journal, ProjectFileDatabase(project), apply=True)['outcome'], 'reconciled')

    def test_binding_raw_inventory_local_identity_and_receipt_tampering_refused(self):
        project, journal, before = self.completed()
        pristine = journal.read_bytes()
        mutations = (
            lambda v: v['route_binding'].update(target_network=252),
            lambda v: v['route_binding'].update(source_network=253),
            lambda v: v['route_binding'].update(source_network=True),
            lambda v: v['route_binding'].update(route=[252]),
            lambda v: v['route_binding'].update(project_sha256='0'*64),
            lambda v: v['route_binding'].update(topology_fresh_at_handoff=False),
            lambda v: v['route_binding'].update(unrecognized=True),
            lambda v: v['before']['initial_mmi'].update(route=[252]),
            lambda v: v['after']['initial_mmi'].update(route=[252]),
            lambda v: v['local_identity'].update(received_hex=''),
            lambda v: v['local_options'].update(received_hex=''),
            lambda v: v['exchange']['receipt'].update(unrecognized=True),
            lambda v: v['exchange'].update(received_hex=(b'g.' + receipt([252], 6, A)).hex()),
            lambda v: v['exchange'].update(bytes_received=0),
            lambda v: v['exchange'].update(correlation_status='unverified'),
            lambda v: v.update(receipt_matches_request=False),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                value = json.loads(pristine); mutate(value); journal.write_text(json.dumps(value))
                with self.assertRaises(ReconcileError): reconcile(journal, ProjectFileDatabase(project), apply=True)
                self.assertEqual(project.read_bytes(), before)
                self.assertFalse(default_record_path(journal).exists())

    def test_wrong_network_and_initial_raw_project_hash_refused(self):
        project, journal, before = self.completed()
        with self.assertRaises(ReconcileError):
            reconcile(journal, ProjectFileDatabase(project), apply=True, network=254)
        project.write_bytes(before + b' ')
        with self.assertRaises(ReconcileError): reconcile(journal, ProjectFileDatabase(project), apply=True)
        self.assertFalse(default_record_path(journal).exists())

    def test_bridge_and_wgate_targets_refused(self):
        for kind in ('BRIDGE2N', 'WGATE'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                self.dir = Path(directory)
                project, journal, before = self.completed(unit_type=kind)
                with self.assertRaises(ReconcileError): reconcile(journal, ProjectFileDatabase(project), apply=True)
                self.assertEqual(project.read_bytes(), before)

    def test_save_freshness_checks_after_candidate_before_write(self):
        project, journal, before = self.completed()
        original = ReconcileRecord.mark_attempted
        def stale(record):
            original(record)
            project.write_bytes(before + b'<!-- concurrent edit -->')
        with patch.object(ReconcileRecord, 'mark_attempted', stale), \
                patch.object(ProjectDocument, 'save', side_effect=AssertionError('overwrote concurrent edit')) as save:
            with self.assertRaises(ReconcileError): reconcile(journal, ProjectFileDatabase(project), apply=True)
        save.assert_not_called()
        self.assertEqual(project.read_bytes(), before + b'<!-- concurrent edit -->')
        self.assertEqual(json.loads(default_record_path(journal).read_text())['phase'], 'db_pending')

    def test_bound_database_unit_guards_refuse_before_record_or_save(self):
        cases = {
            'occupied': lambda raw: raw.replace(b'<Address>21</Address>', b'<Address>6</Address>'),
            'invalid_oid': lambda raw: raw.replace(OID.encode(), b'not-an-oid'),
            'pp_address': lambda raw: raw.replace(b'Value="0xff"', b'Value="0x7"'),
            'text_reference': lambda raw: raw.replace(b'<Partner>', b'<Text>/253/p/255</Text><Partner>'),
        }
        for name, transform in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                self.dir = Path(directory)
                project, journal, before = self.completed(transform=transform)
                with patch.object(ProjectDocument, 'save', side_effect=AssertionError('invalid move saved')):
                    with self.assertRaises(ReconcileError): reconcile(journal, ProjectFileDatabase(project), apply=True)
                self.assertEqual(project.read_bytes(), before)
                self.assertFalse(default_record_path(journal).exists())

    def test_database_type_and_firmware_pins_refuse_before_record(self):
        project, journal, _ = self.completed()
        for options in ({'unit_type': 'KEY4'}, {'firmware': 'wrong'}):
            with self.subTest(options=options), self.assertRaises(ReconcileError):
                reconcile(journal, ProjectFileDatabase(project), apply=True, **options)
        self.assertFalse(default_record_path(journal).exists())

    def test_db_done_reports_later_edit_without_writes(self):
        project, journal, _ = self.completed()
        reconcile(journal, ProjectFileDatabase(project), apply=True)
        project.write_bytes(project.read_bytes() + b'<!-- later edit -->')
        before = project.read_bytes()
        record_path = default_record_path(journal); record_before = record_path.read_bytes()
        with patch.object(ProjectDocument, 'save', side_effect=AssertionError('db_done wrote')):
            result = reconcile(journal, ProjectFileDatabase(project), apply=True)
        self.assertEqual(result['outcome'], 'already_reconciled')
        self.assertFalse(result['current_database_matches_record'])
        self.assertEqual(project.read_bytes(), before)
        self.assertEqual(record_path.read_bytes(), record_before)

    def test_restart_after_write_is_read_only_and_preserves_original_backup(self):
        project, journal, before = self.completed(cbz=True)
        original = ReconcileRecord.advance
        def interrupted(record, phase, **fields):
            if phase == 'db_done': raise KeyboardInterrupt
            return original(record, phase, **fields)
        with patch.object(ReconcileRecord, 'advance', interrupted), self.assertRaises(KeyboardInterrupt):
            reconcile(journal, ProjectFileDatabase(project), apply=True)
        record = json.loads(default_record_path(journal).read_text())
        self.assertEqual(record['phase'], 'db_pending')
        self.assertEqual(Path(record['backup']).read_bytes(), before)
        saved = project.read_bytes()
        with patch.object(ProjectDocument, 'save', side_effect=AssertionError('resume wrote')):
            self.assertEqual(reconcile(journal, ProjectFileDatabase(project), apply=True)['outcome'], 'resumed_complete')
        self.assertEqual(project.read_bytes(), saved)

    def test_directory_sync_failure_stops_and_requires_explicit_recovery(self):
        for fail_after_save in (False, True):
            with self.subTest(fail_after_save=fail_after_save), tempfile.TemporaryDirectory() as directory:
                self.dir = Path(directory)
                project, journal, before = self.completed()
                original = ProjectFileDatabase._sync_parent
                def fail_sync(path):
                    if (Path(path) == project) == fail_after_save:
                        raise OSError('synthetic directory sync failure')
                    return original(path)
                with patch.object(ProjectFileDatabase, '_sync_parent', staticmethod(fail_sync)), \
                        self.assertRaises(ReconcileError):
                    reconcile(journal, ProjectFileDatabase(project), apply=True)
                record = json.loads(default_record_path(journal).read_text())
                self.assertEqual(record['phase'], 'db_pending' if fail_after_save else 'physical_done')
                if not fail_after_save: self.assertEqual(project.read_bytes(), before)
                resumed = reconcile(journal, ProjectFileDatabase(project), apply=True)
                self.assertEqual(resumed['outcome'], 'resumed_complete' if fail_after_save else 'reconciled')

    def test_restart_before_write_and_changed_pending_or_backup_refuse(self):
        for mutation in ('none', 'database', 'backup', 'missing_backup', 'expected_digest', 'unit', 'move', 'path'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                self.dir = Path(directory)
                project, journal, before = self.completed()
                with patch.object(ProjectDocument, 'save', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
                    reconcile(journal, ProjectFileDatabase(project), apply=True)
                path = default_record_path(journal); record = json.loads(path.read_text())
                if mutation == 'database': project.write_bytes(before + b' ')
                elif mutation == 'backup': Path(record['backup']).write_bytes(before + b' ')
                elif mutation == 'missing_backup': Path(record['backup']).unlink()
                elif mutation in ('expected_digest', 'unit', 'move', 'path'):
                    if mutation == 'expected_digest': record['expected_sha256'] = '0'*64
                    elif mutation == 'unit': record['unit']['oid'] = KEEPER
                    elif mutation == 'move': record['move']['target_network'] = 254
                    else: record['unit']['destination_path'] = '/network/254/unit/6'
                    path.write_text(json.dumps(record))
                if mutation == 'none':
                    self.assertEqual(reconcile(journal, ProjectFileDatabase(project), apply=True)['outcome'], 'reconciled')
                else:
                    with self.assertRaises(ReconcileError): reconcile(journal, ProjectFileDatabase(project), apply=True)

    def test_cli_cgate_refused_before_client_construction(self):
        _, journal, _ = self.completed()
        output, error = io.StringIO(), io.StringIO()
        with patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('connected')) as client:
            with redirect_stdout(output), redirect_stderr(error):
                status = cli.main(['serial-address', 'reconcile', '--journal', str(journal),
                                   '--cgate', '127.0.0.1:1', '--project-name', 'HOUSE', '--apply'])
        self.assertEqual(status, 1)
        client.assert_not_called()
        self.assertIn('routed', (output.getvalue() + error.getvalue()).lower())


if __name__ == '__main__':
    unittest.main()
