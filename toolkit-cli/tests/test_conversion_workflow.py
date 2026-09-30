"""Synthetic durable workflow evidence; no vendor specs or physical endpoint."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from cbus_toolkit.cgate import CGateError, CGateResponse
from cbus_toolkit.conversion_workflow import (ConversionWorkflow, ConversionWorkflowError,
                                             load_plan, read_journal, write_plan)


def reply(code=200, lines=None):
    lines = tuple(lines or [f'{code} OK.'])
    return CGateResponse(lines, lines[-1], code)


def unit(address, kind, catalog):
    return (f'<Unit><OID>unit-{address}</OID><Address>{address}</Address><TagName>U{address}</TagName>'
            f'<UnitName>UNIT{address}</UnitName><Description>Keep</Description><SerialNumber>S{address}</SerialNumber>'
            f'<UnitType>{kind}</UnitType><FirmwareVersion>1.0</FirmwareVersion><CatalogNumber>{catalog}</CatalogNumber>'
            f'<DeviceName>D{address}</DeviceName><PP Name="UnitAddress" Value="0x{address:x}" /></Unit>')


class Client:
    host, port = '127.0.0.1', 20023

    def __init__(self):
        self.commands = []
        self.failure = None
        self.documents = {'TEST': ET.fromstring('<Installation><Project><Address>TEST</Address><TagName>TEST</TagName>'
                         '<OID>project</OID><Network><Address>254</Address><OID>network</OID>' +
                         unit(20, 'RELDN4', 'OLD') + unit(21, 'RELDN4A', 'NEW') +
                         '</Network></Project></Installation>')}
        self.persisted = copy.deepcopy(self.documents)

    def command(self, command):
        self.commands.append(command)
        if command.startswith('DBGETXML //'):
            name = command.split('//', 1)[1]
            if name not in self.documents:
                raise CGateError(reply(401))
            raw = ET.tostring(self.documents[name], encoding='unicode')
            return reply(344, ['343-Begin XML snippet', '347-' + raw, '344 End XML snippet'])
        if command.startswith('GET //'):
            path = command.split()[1]
            return reply(300, [f'300-{path}: {name}={value}' for name, value in (
                ('InterfaceState', 'closed'), ('TargetInterfaceState', 'closed'), ('SyncState', 'idle'))])
        if command == 'PROJECT DIR':
            return reply(200, ['123-' + name for name in self.documents] + ['200 OK.'])
        if command.startswith('PROJECT COPY '):
            _, _, source, target = command.split()
            self.documents[target] = copy.deepcopy(self.documents[source])
            for name in ('Address', 'TagName'):
                self.documents[target].find('Project/' + name).text = target
            self.persisted[target] = copy.deepcopy(self.documents[target])
        if command.startswith('CONVERTUNIT CONVERT '):
            network = self.documents['TEST'].find('Project/Network')
            source, target = network.findall('Unit')
            network.remove(source)
            target.find('DeviceName').text = source.findtext('DeviceName')
            target.find('PP').set('Value', '0x14')
            target.find('OID').text = 'new-unit-oid'
            for number in range(1, 5):
                channel = ET.SubElement(target, 'OutputChannel')
                ET.SubElement(channel, 'OID').text = f'channel-{number}'
                ET.SubElement(channel, 'Address').text = str(number)
                ET.SubElement(channel, 'TagName').text = f'Channel{number}'
        if command == 'PROJECT SAVE TEST':
            self.persisted['TEST'] = copy.deepcopy(self.documents['TEST'])
        if command == 'PROJECT LOAD TEST':
            self.documents['TEST'] = copy.deepcopy(self.persisted['TEST'])
        if self.failure and command.startswith(self.failure[0]):
            raise self.failure[1]
        return reply()


class FakeSession:
    def __init__(self, client, path):
        self.path = path
        self.source = '/db' + path
        address = path.rsplit('/', 1)[1]
        self.node = next(item for item in client.documents['TEST'].findall('Project/Network/Unit')
                         if item.findtext('Address') == address)
        self.unit_type = self.node.findtext('UnitType')
        self.firmware = self.node.findtext('FirmwareVersion')

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def info(self, parameter):
        return reply(344, ['347-<Parameters><Param><Name>UnitAddress</Name><Type>int</Type><Address>0</Address></Param></Parameters>', '344 End XML snippet'])

    def export_parameters(self):
        return {'format': 'cbus-cli-parameters-v1', 'unit_type': self.unit_type, 'firmware': self.firmware,
                'catalog_number': self.node.findtext('CatalogNumber'),
                'parameters': {item.get('Name'): item.get('Value') for item in self.node.findall('PP')}}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        for kind in ('RELDN4', 'RELDN4A'):
            (self.path / (kind + '.xml')).write_text('<UnitSpecification><Type>' + kind + '</Type>'
                '<MinVersion>1.0</MinVersion><MaxVersion>1.9</MaxVersion><Parameters><Param>'
                '<Name>UnitAddress</Name><Type>int</Type><Address>0</Address><DefaultValue>0</DefaultValue>'
                '</Param></Parameters></UnitSpecification>')
        (self.path / 'ConvertUnitMappingTable.xml').write_text('<UnitConversions><UnitConversion>'
            '<Unit_type_Old>RELDN4</Unit_type_Old><Unit_type_New>RELDN4A</Unit_type_New>'
            '</UnitConversion></UnitConversions>')
        catalog = '<CBusUnits><Units>'
        for number, kind in [('OLD', 'RELDN4'), ('NEW', 'RELDN4A')]:
            catalog += (f'<Unit><CatalogNumber>{number}</CatalogNumber><OutputCount>4</OutputCount>'
                        f'<FirmwareRevisions><Revision><UnitType>{kind}</UnitType><MinVersion>1.0</MinVersion>'
                        f'<MaxVersion>1.9</MaxVersion><UnitSpecName>{kind}.xml</UnitSpecName>'
                        '<IsDefault>true</IsDefault><ClassName>CBus3DinRelayUnit</ClassName>'
                        '</Revision></FirmwareRevisions></Unit>')
        (self.path / 'cbusunits.xml').write_text(catalog + '</Units></CBusUnits>')
        self.client = Client()
        self.workflow = ConversionWorkflow(self.client, self.path)
        self.patch = patch('cbus_toolkit.conversion_workflow.Programmer.load',
                           side_effect=lambda network, source: FakeSession(self.client, source[3:]))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.journal = self.path / 'attempt.json'

    def plan(self):
        return self.workflow.plan_move('//TEST/254/p/20', '//TEST/254/p/21', backup_project='BACKUP',
                                       exclusive_project=True)

    def apply(self, plan):
        return self.workflow.apply_move(plan, journal=self.journal, exclusive_project=True)

    def test_independent_plan_backed_up_save_reopen_and_private_files(self):
        plan = self.plan()
        self.assertEqual(plan['binding']['expected_pp'], [['UnitAddress', '0x14']])
        self.assertEqual(len(plan['binding']['expected_identity']['OutputChannels']), 4)
        review = self.path / 'review.json'
        write_plan(review, plan)
        self.assertEqual(load_plan(review), plan)
        self.assertEqual(review.stat().st_mode & 0o777, 0o600)
        result = self.apply(plan)
        self.assertTrue(result['complete'])
        self.assertFalse(result['hardware_programmed'])
        self.assertEqual(self.client.commands.count('PROJECT SAVE TEST'), 1)
        self.assertEqual(self.client.commands.count('CONVERTUNIT CONVERT 2 //TEST/254/p/20 //TEST/254/p/21'), 1)
        self.assertEqual(read_journal(self.journal)['phase'], 'complete')
        self.assertEqual(self.journal.stat().st_mode & 0o777, 0o600)
        before = len(self.client.commands)
        recovered = ConversionWorkflow(self.client).recover(journal=self.journal)
        self.assertTrue(recovered['persistence_verified'])
        self.assertTrue(all(command.startswith('DBGETXML ') for command in self.client.commands[before:]))

    def test_convert_keyboard_interrupt_retains_possible_phase_and_no_replay(self):
        plan = self.plan()
        self.client.failure = ('CONVERTUNIT CONVERT', KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.apply(plan)
        self.assertEqual(read_journal(self.journal)['phase'], 'convert-possible')
        self.client.failure = None
        recovered = ConversionWorkflow(self.client).recover(journal=self.journal)
        self.assertEqual(recovered['disposition'], 'observed-converted')
        self.assertIsNone(recovered['project_saved'])
        with self.assertRaises(ConversionWorkflowError):
            self.apply(plan)
        with self.assertRaises(ConversionWorkflowError):
            self.workflow.apply_move(plan, journal=self.path / 'other.json', exclusive_project=True)
        self.assertEqual(sum(command.startswith('CONVERTUNIT CONVERT') for command in self.client.commands), 1)

    def test_save_disconnect_does_not_infer_durability_from_current_tree(self):
        plan = self.plan()
        self.client.failure = ('PROJECT SAVE TEST', RuntimeError('lost reply'))
        with self.assertRaisesRegex(RuntimeError, 'lost reply'):
            self.apply(plan)
        self.assertEqual(read_journal(self.journal)['phase'], 'save-possible')
        self.client.failure = None
        recovered = ConversionWorkflow(self.client).recover(journal=self.journal)
        self.assertEqual(recovered['disposition'], 'observed-converted')
        self.assertFalse(recovered['persistence_verified'])
        self.assertIsNone(recovered['project_saved'])
        self.assertEqual(self.client.commands.count('PROJECT SAVE TEST'), 1)

    def test_stale_unrelated_content_refuses_before_copy_convert_or_save(self):
        plan = self.plan()
        self.client.documents['TEST'].find('Project/TagName').text = 'changed'
        with self.assertRaisesRegex(ConversionWorkflowError, 'changed'):
            self.apply(plan)
        self.assertFalse(any(command.startswith(('PROJECT COPY', 'CONVERTUNIT CONVERT', 'PROJECT SAVE'))
                             for command in self.client.commands))
        self.assertFalse(self.journal.exists())

    def test_wrong_endpoint_and_tampered_plan_are_refused(self):
        plan = self.plan()
        self.client.port += 1
        with self.assertRaisesRegex(ValueError, 'endpoint'):
            self.apply(plan)
        self.client.port -= 1
        plan['binding']['expected_pp'][0][1] = '0x15'
        with self.assertRaisesRegex(ValueError, 'hash'):
            self.apply(plan)

    def test_backup_failure_and_invalid_pp_never_convert(self):
        plan = self.plan()
        self.client.failure = ('PROJECT COPY', RuntimeError('copy reply lost'))
        with self.assertRaises(RuntimeError):
            self.apply(plan)
        self.assertEqual(read_journal(self.journal)['phase'], 'backup-copy-possible')
        self.assertFalse(any(command.startswith('CONVERTUNIT CONVERT') for command in self.client.commands))
        self.client.failure = None
        self.client.documents['TEST'].find('Project/Network/Unit/PP').set('Value', 'garbage')
        with self.assertRaisesRegex(ValueError, 'PP'):
            self.workflow.plan_move('//TEST/254/p/20', '//TEST/254/p/21', backup_project='OTHER',
                                    exclusive_project=True)

    def test_recovery_changed_tree_is_conflict_and_read_failure_is_retained(self):
        plan = self.plan()
        self.apply(plan)
        self.client.documents['TEST'].find('Project/TagName').text = 'someone edited it'
        observed = ConversionWorkflow(self.client).recover(journal=self.journal)
        self.assertEqual(observed['disposition'], 'conflict')
        self.assertFalse(observed['persistence_verified'])
        with patch.object(self.client, 'command', side_effect=RuntimeError('server unavailable')):
            unavailable = ConversionWorkflow(self.client).recover(journal=self.journal)
        self.assertEqual(unavailable['disposition'], 'read-unavailable')
        self.assertEqual(unavailable['observation']['read_error']['message'], 'server unavailable')

    def test_original_interrupt_survives_journal_update_failure(self):
        plan = self.plan()
        self.client.failure = ('CONVERTUNIT CONVERT', KeyboardInterrupt('operator stopped'))
        from cbus_toolkit.pci_selected_serial import _Journal
        original = _Journal.write
        def fail_error_update(writer, state):
            if state.get('error') is not None:
                raise OSError('journal filesystem unavailable')
            return original(writer, state)
        with patch.object(_Journal, 'write', fail_error_update):
            with self.assertRaises(KeyboardInterrupt) as captured:
                self.apply(plan)
        self.assertEqual(captured.exception.details['phase'], 'convert-possible')
        self.assertIn('journal_update_error', captured.exception.details)
        self.assertEqual(read_journal(self.journal)['phase'], 'convert-possible')

    def test_corrupt_unresolved_non_json_filename_blocks_new_attempt(self):
        plan = self.plan()
        (self.path / 'previous.attempt').write_text('broken cbus-native-conversion-move-journal-v1')
        with self.assertRaisesRegex(ValueError, 'Corrupted'):
            self.apply(plan)
        self.assertFalse(self.journal.exists())

    def test_allocator_ids_must_survive_reopen(self):
        plan = self.plan()
        original = self.client.command
        def mutate_after_load(command):
            result = original(command)
            if command == 'PROJECT LOAD TEST':
                self.client.documents['TEST'].find('Project/Network/Unit/OID').text = 'changed-oid'
            return result
        self.client.command = mutate_after_load
        with self.assertRaisesRegex(ConversionWorkflowError, 'Reopened'):
            self.apply(plan)
        self.assertEqual(read_journal(self.journal)['phase'], 'reopen-possible')

    def test_mixed_content_and_scalar_attributes_refuse_before_mutation(self):
        self.client.documents['TEST'].find('Project/Network/Address').tail = 'retain-me'
        with self.assertRaisesRegex(ValueError, 'mixed XML'):
            self.plan()
        self.client.documents['TEST'].find('Project/Network/Address').tail = None
        self.client.documents['TEST'].findall('Project/Network/Unit')[1].find('UnitName').set('vendor', 'x')
        with self.assertRaisesRegex(ValueError, 'scalar attributes'):
            self.plan()
        self.assertFalse(any(command.startswith(('PROJECT COPY', 'CONVERTUNIT CONVERT', 'PROJECT SAVE'))
                             for command in self.client.commands))

    def test_recovery_reads_backup_and_reports_corruption_or_missing(self):
        plan = self.plan()
        self.apply(plan)
        recovered = ConversionWorkflow(self.client).recover(journal=self.journal)
        self.assertTrue(recovered['backup_verified_fresh'])
        self.assertTrue(recovered['source_removed'])
        self.client.documents['BACKUP'].find('Project/Network/Unit/UnitName').text = 'altered'
        changed = ConversionWorkflow(self.client).recover(journal=self.journal)
        self.assertTrue(changed['observation']['matched'])
        self.assertFalse(changed['backup_verified_fresh'])
        self.assertFalse(changed['persistence_verified'])
        self.assertIsNone(changed['project_saved'])
        del self.client.documents['BACKUP']
        missing = ConversionWorkflow(self.client).recover(journal=self.journal)
        self.assertEqual(missing['backup_presence'], 'missing')
        self.assertFalse(missing['backup_verified_fresh'])

    def test_duplicate_json_refuses_without_server_io(self):
        path = self.path / 'review.json'
        path.write_text('{"format":1,"format":2}')
        with self.assertRaises(ValueError):
            load_plan(path)


if __name__ == '__main__':
    unittest.main()
