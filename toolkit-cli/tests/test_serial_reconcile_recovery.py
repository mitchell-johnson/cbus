"""Fresh read-only recovery after one actual, uncertain selected-serial send."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from cbus_toolkit import cli
from cbus_toolkit.pci_selected_serial import (
    SelectedSerialUncertain, export_verification, recovery_binding,
)
from cbus_toolkit.pci_serial_address_transport import PCISerialAddressTransport
from cbus_toolkit.project import ProjectDocument
from cbus_toolkit.serial_reconcile import (
    CGateDatabase, ProjectFileDatabase, ReconcileError, default_record_path, reconcile, verify_journal,
)
from tests.test_pci_selected_serial import manager
from tests.test_serial_reconcile import OID, PROJECT, run_move, write_project
from tests.test_simulator_duplicate_addressing import A, CO_A, fixture


class VerificationHandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)

    def handoff(self):
        sim = fixture(state_path=self.directory / 'physical.json')
        journal = self.directory / 'apply.json'
        target = self.directory / 'verification.json'
        original_command = sim._command

        def malformed(line, context):
            # Move through the independently modeled fixture, then put malformed
            # bytes on the socket. Production capture/evidence remains intact.
            response, confirmation = original_command(line, context)
            if line == CO_A.rstrip(b'\r'):
                response = b'XX\r\n' + response
            return response, confirmation

        with sim.running() as endpoint:
            subject = manager(endpoint)
            plan = subject.plan(A, 6)
            with patch.object(sim, '_command', malformed):
                with self.assertRaises(SelectedSerialUncertain):
                    subject.apply(plan, recovery_path=journal)
            self.assertEqual(len(sim.co_operations), 1)
            self.assertEqual(sim.snapshot()['physical_nodes'][A]['address'], 6)
            old = journal.read_bytes()
            marker = Path(json.loads(old)['attempt_identity'])
            marker_old = marker.read_bytes()
            with self.assertRaises(ReconcileError):
                verify_journal(journal)
            binding = recovery_binding(journal)
            with patch.object(PCISerialAddressTransport, 'send_serial_address',
                              side_effect=AssertionError('verification replayed CO')):
                result = subject.verify(subject.load_recovery(journal))
            self.assertTrue(result.observed_expected_change)
            export_verification(target, binding, result)
        self.assertEqual(journal.read_bytes(), old)
        self.assertEqual(marker.read_bytes(), marker_old)
        self.assertEqual(len(sim.co_operations), 1)
        requests = [bytes.fromhex(row['hex']) for row in sim.wire_log if row['direction'] == 'rx']
        self.assertEqual(sum(CO_A.rstrip(b'\r') in request for request in requests), 1)
        return journal, marker, target, sim

    def test_uncertain_send_fresh_handoff_and_offline_preservation(self):
        journal, marker, target, sim = self.handoff()
        originals = {path: path.read_bytes() for path in (journal, marker, target)}
        move = verify_journal(target)
        self.assertFalse(move.receipt_matches_request)
        project = write_project(self.directory)
        before = project.read_bytes()
        self.assertEqual(reconcile(target, ProjectFileDatabase(project))['outcome'], 'planned')
        self.assertEqual(project.read_bytes(), before)
        result = reconcile(target, ProjectFileDatabase(project), apply=True)
        self.assertEqual(result['outcome'], 'reconciled')
        self.assertFalse(result['bus_io_performed'])
        document = ProjectDocument.load(project)
        self.assertEqual(document.path_of(document.resolve('oid:' + OID)), '/network/254/unit/6')
        document.update('/network/254/unit/6', {'Address': '255'})
        document.set_parameter('/network/254/unit/255', 'UnitAddress', '0xff')
        self.assertEqual(document.raw_xml(), ProjectDocument.from_snapshot(before).raw_xml())
        for path, raw in originals.items():
            self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(len(sim.co_operations), 1)

    def test_tampered_bindings_raw_inventory_flags_and_plan_refuse_before_write(self):
        journal, marker, target, _ = self.handoff()
        originals = {path: path.read_bytes() for path in (journal, marker, target)}
        project = write_project(self.directory)
        project_before = project.read_bytes()
        mutations = (
            ('original', lambda v: v['original'].update(sha256='0' * 64)),
            ('raw_inventory', lambda v: v['verification']['after']['initial_mmi'].update(received_hex='')),
            ('replayed', lambda v: v.update(address_command_replayed=True)),
            ('modified', lambda v: v.update(original_journal_modified=True)),
            ('plan', lambda v: v['verification']['plan'].update(destination=7)),
        )
        for name, mutate in mutations:
            with self.subTest(name=name):
                value = json.loads(originals[target]); mutate(value)
                target.write_text(json.dumps(value))
                with self.assertRaises(ReconcileError):
                    reconcile(target, ProjectFileDatabase(project), apply=True)
                self.assertEqual(project.read_bytes(), project_before)
                self.assertFalse(default_record_path(target).exists())
        target.write_bytes(originals[target])
        for path in (journal, marker):
            with self.subTest(changed_file=path.name):
                path.write_bytes(originals[path] + b' ')
                with self.assertRaises(ReconcileError):
                    reconcile(target, ProjectFileDatabase(project), apply=True)
                path.write_bytes(originals[path])
                self.assertEqual(project.read_bytes(), project_before)
                self.assertFalse(default_record_path(target).exists())

    def test_cli_output_with_plan_refuses_before_io(self):
        output, error = io.StringIO(), io.StringIO()
        destination = self.directory / 'output.json'
        with patch('cbus_toolkit.pci_selected_serial.SelectedSerialCoordinator',
                   side_effect=AssertionError('constructed coordinator')) as coordinator:
            with redirect_stdout(output), redirect_stderr(error):
                status = cli.main(['serial-address', 'verify', '--plan',
                    str(self.directory / 'absent-plan.json'), '--output', str(destination)])
        self.assertEqual(status, 1)
        coordinator.assert_not_called()
        self.assertFalse(destination.exists())
        self.assertIn('--recovery', output.getvalue() + error.getvalue())

    def test_cli_missing_exclusive_project_refuses_before_cgate_connection(self):
        _, _, target, _ = self.handoff()
        output, error = io.StringIO(), io.StringIO()
        with patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('connected')) as client:
            with redirect_stdout(output), redirect_stderr(error):
                status = cli.main(['serial-address', 'reconcile', '--journal', str(target),
                    '--cgate', '127.0.0.1:1', '--project-name', 'SYNTH', '--apply'])
        self.assertEqual(status, 1)
        client.assert_not_called()
        self.assertIn('exclusive-project', output.getvalue() + error.getvalue())


@unittest.skipUnless(os.environ.get('CBUS_CMQTTD_BIN'), 'explicit owned cmqttd binary required')
class CGateRecoveryGuardTests(unittest.TestCase):
    """Early uncertain operations and foreign edits must not authorize replay."""

    def setUp(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeProjects
        from cbus_toolkit.programming import xml_text
        from research.cgate_dbsetxml_unit_differential import owned_server

        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        # Own the physical evidence for this case. Another selected test module
        # may already have torn down its cached Journals directory.
        self.journal, moved, _ = run_move(self.directory)
        self.assertEqual(moved.outcome, 'observed_expected_change')
        self.original_journal = self.journal.read_bytes()
        self.marker = Path(json.loads(self.original_journal)['attempt_identity'])
        self.original_marker = self.marker.read_bytes()
        binary = Path(os.environ['CBUS_CMQTTD_BIN']).resolve()
        self.port = self.enterContext(owned_server('cmqttd', binary))
        self.client = self.enterContext(CGateClient('127.0.0.1', self.port, timeout=15))
        projects = NativeProjects(self.client)
        projects.operation('new', 'SYNTH')
        projects.operation('use', 'SYNTH')
        self.client.command('DBCREATENET 254 Owned Cni 127.0.0.1:1')
        from cbus_toolkit.native import NativeDatabase
        network = ET.fromstring(xml_text(NativeDatabase(self.client).get('//SYNTH/254', xml=True)))
        for unit in ET.fromstring(PROJECT).findall('Project/Network/Unit'):
            for child in list(unit):
                if child.tag.startswith('{') or child.tag == 'Partner':
                    unit.remove(child)
            if unit.find('UnitName') is None:
                ET.SubElement(unit, 'UnitName').text = 'KEYE1'
            if unit.findtext('Address') == '20':
                ET.SubElement(unit, 'Description').text = OID
            network.append(unit)
        self.client.command_document('DBSETXML //SYNTH/254', ET.tostring(network, encoding='unicode'))
        projects.operation('save', 'SYNTH')
        projects.operation('close', 'SYNTH')
        projects.operation('load', 'SYNTH')
        projects.operation('use', 'SYNTH')
        self.baseline_network = xml_text(NativeDatabase(self.client).get('//SYNTH/254', xml=True))
        self.calls = []
        command, document = self.client.command, self.client.command_document

        def recorded(text):
            self.calls.append(text)
            return command(text)

        def recorded_document(text, body):
            self.calls.append(text)
            return document(text, body)

        self.client.command = recorded
        self.client.command_document = recorded_document
        self.addCleanup(self.assert_physical_evidence_unchanged)

    def assert_physical_evidence_unchanged(self):
        self.assertEqual(self.journal.read_bytes(), self.original_journal)
        self.assertEqual(self.marker.read_bytes(), self.original_marker)

    def database(self):
        return CGateDatabase(self.client, 'SYNTH', endpoint=f'127.0.0.1:{self.port}',
                             exclusive_project=True)

    def snapshot(self):
        document, _ = self.database().snapshot()
        return document.raw_xml()

    def assert_no_mutation_or_save(self, calls):
        self.assertFalse(any(row.startswith(('DBSETXML ', 'PROJECT SAVE ', 'PROJECT COPY '))
                             for row in calls), calls)

    def reset_database(self):
        from cbus_toolkit.native import NativeProjects
        self.client.command_document('DBSETXML //SYNTH/254', self.baseline_network)
        NativeProjects(self.client).operation('save', 'SYNTH')
        self.calls.clear()

    def early_fault(self, action, position):
        from cbus_toolkit.native import NativeProjects
        original = NativeProjects.operation
        fired = []

        def interrupt(manager, operation, project, other=None, **kwargs):
            if operation == action and project == 'SYNTH' and not fired:
                fired.append(True)
                if position == 'before':
                    raise KeyboardInterrupt('owned early-operation interruption')
                original(manager, operation, project, other, **kwargs)
                raise KeyboardInterrupt('owned early-operation lost reply')
            return original(manager, operation, project, other, **kwargs)

        record = self.directory / f'{action}-{position}.json'
        with patch.object(NativeProjects, 'operation', interrupt), patch.object(
                PCISerialAddressTransport, 'send_serial_address',
                side_effect=AssertionError('database recovery replayed address command')):
            with self.assertRaises(KeyboardInterrupt):
                reconcile(self.journal, self.database(), apply=True, record_path=record, network=254)
        self.assertTrue(fired)
        pending = json.loads(record.read_text())
        self.assertEqual(pending['phase'], 'db_pending')
        self.assertFalse(pending['cgate']['backup_confirmed'])
        self.assertFalse(pending['cgate']['saved_readback_verified'])
        self.assertFalse(any(row.startswith('DBSETXML ') for row in self.calls))
        backup_before = pending['backup']
        original_project = self.snapshot()
        self.calls.clear()
        with self.assertRaisesRegex(ReconcileError, 'Saved project remains the original'):
            reconcile(self.journal, self.database(), apply=True, record_path=record, network=254)
        self.assert_no_mutation_or_save(self.calls)
        self.assertEqual(self.snapshot(), original_project)
        self.calls.clear()
        with patch.object(PCISerialAddressTransport, 'send_serial_address',
                          side_effect=AssertionError('database-only retry replayed address command')):
            result = reconcile(self.journal, self.database(), apply=True, record_path=record,
                               network=254, retry_database=True)
        self.assertEqual(result['outcome'], 'reconciled')
        completed = json.loads(record.read_text())
        self.assertEqual(completed['phase'], 'db_done')
        self.assertTrue(completed['cgate']['saved_readback_verified'])
        self.assertNotEqual(completed['backup'], backup_before)
        self.assertEqual(sum(row.startswith('DBSETXML ') for row in self.calls), 1)
        self.assertEqual(sum(row.startswith('PROJECT COPY ') for row in self.calls), 1)
        self.assertEqual(sum(row.startswith('PROJECT SAVE ') for row in self.calls), 2)
        self.calls.clear()
        again = reconcile(self.journal, self.database(), apply=True, record_path=record, network=254)
        self.assertEqual(again['outcome'], 'already_reconciled')
        self.assert_no_mutation_or_save(self.calls)

    def test_baseline_save_faults_require_saved_original_and_explicit_database_retry(self):
        for position in ('before', 'after'):
            with self.subTest(position=position):
                self.reset_database()
                self.early_fault('save', position)

    def test_backup_copy_faults_do_not_overwrite_uncertain_copy_or_replay(self):
        for position in ('before', 'after'):
            with self.subTest(position=position):
                self.reset_database()
                self.early_fault('copy', position)

    def test_loaded_foreign_edit_refuses_recovery_before_close_or_save(self):
        from cbus_toolkit.native import NativeProjects
        original = NativeProjects.operation
        saves = []

        def before_target_save(manager, operation, project, other=None, **kwargs):
            if operation == 'save' and project == 'SYNTH':
                saves.append(True)
                if len(saves) == 2:
                    raise KeyboardInterrupt('owned interruption before target save')
            return original(manager, operation, project, other, **kwargs)

        record = self.directory / 'foreign-edit.json'
        with patch.object(NativeProjects, 'operation', before_target_save):
            with self.assertRaises(KeyboardInterrupt):
                reconcile(self.journal, self.database(), apply=True, record_path=record, network=254)
        before_foreign_edit = self.snapshot()
        self.client.command('DBSET //SYNTH/254/p/20/Description Foreign edit')
        foreign = self.snapshot()
        self.assertNotEqual(foreign, before_foreign_edit)
        self.assertIn('<Description>Foreign edit</Description>', foreign)
        record_before = record.read_bytes()
        self.calls.clear()
        with self.assertRaisesRegex(ReconcileError, 'Loaded project changed outside'):
            reconcile(self.journal, self.database(), apply=True, record_path=record, network=254)
        self.assert_no_mutation_or_save(self.calls)
        self.assertFalse(any(row.startswith('PROJECT CLOSE ') for row in self.calls), self.calls)
        self.assertEqual(self.snapshot(), foreign)
        self.assertEqual(record.read_bytes(), record_before)

    def test_open_or_busy_runtime_refuses_before_record_or_database_write(self):
        from cbus_toolkit.addressing import NetworkAddressing
        original = NetworkAddressing._runtime
        before = self.snapshot()
        for field, value in (('InterfaceState', 'running'), ('TargetInterfaceState', 'running'),
                             ('SyncState', 'running')):
            with self.subTest(field=field):
                def injected_runtime(manager, path):
                    runtime = dict(original(manager, path))
                    runtime[field] = value
                    return tuple(runtime.items())
                self.calls.clear()
                with patch.object(NetworkAddressing, '_runtime', injected_runtime):
                    with self.assertRaisesRegex(ValueError, 'closed interface'):
                        reconcile(self.journal, self.database(), apply=True, network=254)
                self.assert_no_mutation_or_save(self.calls)
                self.assertFalse(default_record_path(self.journal).exists())
                self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
