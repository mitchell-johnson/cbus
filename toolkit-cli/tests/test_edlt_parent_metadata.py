"""Native project metadata resolution for the eDLT parent transaction."""
from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
import os
from types import SimpleNamespace
import unittest
from uuid import UUID
from xml.sax.saxutils import escape, quoteattr

from cbus_toolkit.addressing import _RUNTIME_FIELDS
from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_parent_metadata import (
    NativeEdltParentError, NativeEdltParentTransaction,
    plan_native_parent_metadata,
)
from cbus_toolkit.edlt_parent_transaction import EdltParentTransaction
from tests.test_edlt import Session
from tests.test_edlt_parent_form import fixture
from tests.test_edlt_parent_transaction import activation, lighting, measurement


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'research/fixtures/edlt-parent-metadata-evidence.json'
ACCEPTANCE = ROOT / 'research/fixtures/edlt-parent-metadata-acceptance.json'


def oid(value):
    return str(UUID(int=value))


def response(code=200, message='OK.'):
    line = str(code) + ' ' + message
    return CGateResponse((line,), line, code)


class NativeSession(Session):
    source = '/db//TEST/254/p/20'

    def __init__(self, spec, client):
        super().__init__(spec)
        self.client = client
        self.programmer = SimpleNamespace(client=client)
        self.save_error = None

    def __enter__(self):
        self.current = deepcopy(self.client.values)
        return self

    def __exit__(self, *_):
        return False

    def save_to_source(self):
        self.client.commands.append('PP SAVE')
        self.client.values = deepcopy(self.current)
        if self.save_error is not None:
            raise self.save_error
        return response()


class FakeProgrammer:
    def __init__(self, session):
        self.session = session
        self.calls = []

    def load(self, lock, source):
        self.calls.append((lock, source))
        return self.session


class MetadataClient:
    connected = True

    def __init__(self, spec, *, applications=None):
        self.values = spec.defaults()
        self.applications = deepcopy(applications if applications is not None else {
            56: {'oid': oid(56), 'tag': 'Lighting', 'groups': {}},
            202: {'oid': oid(202), 'tag': 'Trigger Control', 'groups': {}},
        })
        self.saved_values = deepcopy(self.values)
        self.saved_applications = deepcopy(self.applications)
        self.backups = {}
        self.commands = []
        self.next_oid = 10000
        self.failure = None

    def _new_oid(self):
        self.next_oid += 1
        return oid(self.next_oid)

    def _group_xml(self, application, address, group):
        tags = ''.join(
            '<TagDLT><LanguageID>' + str(row.get('language', 1))
            + '</LanguageID><FlavourID>' + str(row['variant'] + 1)
            + '</FlavourID><TagType>' + row['type'] + '</TagType><TagValue>'
            + escape(row.get('value', '')) + '</TagValue></TagDLT>'
            for row in group.get('tags', ()))
        levels = ''
        for level in group.get('levels', ()):
            level_tags = ''.join(
                '<TagDLT><LanguageID>' + str(row.get('language', 1))
                + '</LanguageID><FlavourID>' + str(row['variant'] + 1)
                + '</FlavourID><TagType>' + row['type']
                + '</TagType><TagValue>' + escape(row.get('value', ''))
                + '</TagValue></TagDLT>'
                for row in group.get('level_tags', {}).get(level, ()))
            identity = group.get('level_oids', {}).get(
                level, oid(20000 + application * 256 + address * 16 + level))
            name = group.get('level_names', {}).get(level, 'Level ' + str(level))
            value = group.get('level_values', {}).get(level, level)
            levels += ('<Level Value="' + str(value) + '"><OID>' + identity
                       + '</OID><TagName>' + escape(name)
                       + '</TagName><Address>' + str(level) + '</Address>'
                       + ('<TagsDLT>' + level_tags + '</TagsDLT>'
                          if level_tags else '') + '</Level>')
        kind = group.get('kind', 'NetVar' if application == 203 else 'Group')
        return ('<' + kind + '><OID>' + group['oid'] + '</OID><TagName>'
                + escape(group['tag']) + '</TagName><Address>' + str(address)
                + '</Address><Notes>retained</Notes>'
                + ('<TagsDLT>' + tags + '</TagsDLT>' if tags else '')
                + levels + '</' + kind + '>')

    def xml(self):
        applications = []
        for address, application in sorted(self.applications.items()):
            groups = ''.join(self._group_xml(address, group_address, group)
                             for group_address, group in sorted(application['groups'].items()))
            applications.append(
                '<Application><OID>' + application['oid'] + '</OID><TagName>'
                + escape(application['tag']) + '</TagName><Address>' + str(address)
                + '</Address><Description>retained</Description>' + groups
                + '</Application>')
        pp = ''.join('<PP Name=' + quoteattr(name) + ' Value=' + quoteattr(value) + '/>'
                     for name, value in self.values.items())
        return ('<Installation><Project><Address>TEST</Address>'
                '<Network><Address>254</Address><InterfaceType>CNI</InterfaceType>'
                + ''.join(applications)
                + '<Unit><OID>' + oid(999) + '</OID><TagName>eDLT</TagName>'
                '<Address>20</Address><UnitType>KEYGL5</UnitType>'
                '<FirmwareVersion>5.5.00</FirmwareVersion>'
                '<CatalogNumber>5055EDL</CatalogNumber><Notes>preserved</Notes>'
                + pp + '</Unit></Network></Project></Installation>')

    @staticmethod
    def _xml_reply(value):
        lines = ('343-Begin XML snippet', '347-' + value, '344 End XML snippet')
        return CGateResponse(lines, lines[-1], 344)

    def command(self, command):
        self.commands.append(command)
        if self.failure is not None:
            result = self.failure(command)
            if isinstance(result, BaseException):
                raise result
            if result is not None:
                return result
        if command == 'DBGETXML //TEST':
            return self._xml_reply(self.xml())
        if command.startswith('DBGET //TEST/254/p/20/'):
            field = command.rsplit('/', 1)[1]
            identities = {'UnitType': 'KEYGL5', 'FirmwareVersion': '5.5.00',
                          'CatalogNumber': '5055EDL'}
            if field in identities:
                return response(342, command[6:] + '=' + identities[field])
        if command == 'GET //TEST/254 *':
            values = {name: 'fixture' for name in _RUNTIME_FIELDS}
            values.update(InterfaceState='closed', TargetInterfaceState='closed',
                          SyncState='idle')
            lines = tuple('300' + (' ' if index == len(values) - 1 else '-')
                          + '//TEST/254: ' + name + '=' + value
                          for index, (name, value) in enumerate(values.items()))
            return CGateResponse(lines, lines[-1], 300)
        match = __import__('re').fullmatch(
            r'DBGET !([0-9a-fA-F-]{36})/OID', command)
        if match:
            identity = match[1]
            for application in self.applications.values():
                for group in application['groups'].values():
                    if identity in group.get('level_oids', {}).values():
                        return response(342, command[6:] + '=' + identity)
            return response(401, 'Unknown OID')
        match = __import__('re').fullmatch(
            r'DBSETSAFE !([0-9a-fA-F-]{36})/Value ([0-9]+)', command)
        if match:
            identity, value = match[1], int(match[2])
            for application in self.applications.values():
                for group in application['groups'].values():
                    for address, candidate in group.get(
                            'level_oids', {}).items():
                        if candidate == identity:
                            group.setdefault('level_values', {})[
                                address] = value
                            return response()
            return response(401, 'Unknown OID')
        if command == 'PROJECT SAVE TEST':
            self.saved_values = deepcopy(self.values)
            self.saved_applications = deepcopy(self.applications)
            return response()
        if command.startswith('PROJECT COPY TEST '):
            name = command.rsplit(' ', 1)[1]
            if name in self.backups:
                return response(401, 'Already exists')
            self.backups[name] = (deepcopy(self.saved_values),
                                  deepcopy(self.saved_applications))
            return response()
        if command in ('PROJECT USE TEST', 'PROJECT CLOSE TEST'):
            return response()
        if command == 'PROJECT LOAD TEST':
            self.values = deepcopy(self.saved_values)
            self.applications = deepcopy(self.saved_applications)
            return response()
        match = __import__('re').fullmatch(
            r'DBADDSAFE //TEST/254 Application ([0-9]+) (.+)', command)
        if match:
            address = int(match[1]); identity = self._new_oid()
            self.applications[address] = {
                'oid': identity, 'tag': match[2], 'groups': {}}
            return response(301, 'OID=' + identity)
        match = __import__('re').fullmatch(
            r'DBADDSAFE //TEST/254/([0-9]+) (Group|NetVar) ([0-9]+) (.+)',
            command)
        if match:
            application, kind, address = int(match[1]), match[2], int(match[3])
            identity = self._new_oid()
            self.applications[application]['groups'][address] = {
                'oid': identity, 'tag': match[4], 'kind': kind, 'levels': ()}
            return response(301, 'OID=' + identity)
        match = __import__('re').fullmatch(
            r'DBADDSAFE //TEST/254/([0-9]+)/([0-9]+) Level ([0-9]+) (.+)',
            command)
        if match:
            application, group_address, address = map(
                int, match.group(1, 2, 3))
            group = self.applications[application]['groups'][group_address]
            if address in group.get('levels', ()):
                return response(401, 'Level address already exists')
            identity = self._new_oid()
            group['levels'] = tuple(sorted((*group.get('levels', ()), address)))
            group.setdefault('level_oids', {})[address] = identity
            group.setdefault('level_names', {})[address] = match[4]
            group.setdefault('level_values', {})[address] = 0
            return response(301, 'OID=' + identity)
        if command.startswith('DBDELETE !'):
            identity = command[len('DBDELETE !'):]
            for application, row in list(self.applications.items()):
                if row['oid'] == identity:
                    if row['groups']:
                        return response(401, 'Application is not empty')
                    del self.applications[application]
                    return response()
                for address, group in list(row['groups'].items()):
                    if group['oid'] == identity:
                        del row['groups'][address]
                        return response()
                    for level, candidate in list(
                            group.get('level_oids', {}).items()):
                        if candidate == identity:
                            group['levels'] = tuple(
                                value for value in group.get('levels', ())
                                if value != level)
                            for key in ('level_oids', 'level_names',
                                        'level_values'):
                                group.get(key, {}).pop(level, None)
                            return response()
            return response(401, 'Unknown OID')
        raise AssertionError('Unexpected command: ' + command)


class ParentMetadataTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = EdltParentTransaction(self.spec)
        self.client = MetadataClient(self.spec)
        self.operations = (measurement(), lighting(), activation())
        self.values = self.editor.snapshot(self.client.values)

    def offline(self, **kwargs):
        return plan_native_parent_metadata(
            self.client.xml(), '//TEST/254/p/20', self.values,
            self.editor, self.operations, **kwargs)

    def test_project_snapshot_derives_cache_creations_and_all_static_labels(self):
        plan = self.offline()
        document = plan.as_dict()
        self.assertEqual(document['format'],
                         'cbus-native-edlt-parent-metadata-plan-v1')
        self.assertEqual(
            [(row.kind, row.application, row.address) for row in plan.creations],
            [('Application', 203, 203), ('Group', 56, 12),
             ('Group', 56, 42)])
        self.assertEqual(document['static_labels']['count'], 64)
        self.assertTrue(document['static_labels']['complete'])
        self.assertEqual(document['metadata_provenance'],
                         'one-admitted-native-project-xml-snapshot')
        self.assertEqual(document['parent_transaction']['format'],
                         'cbus-edlt-parent-transaction-plan-v1')
        self.assertFalse(document['batch_atomic'])
        self.assertFalse(document['physical_device_programmed'])
        self.assertEqual(plan.cache.find(202, 255).levels, ())

    def test_existing_group_levels_and_safe_text_labels_are_derived(self):
        self.client.applications[202]['groups'][42] = {
            'oid': oid(420), 'tag': 'Trigger', 'levels': (2, 7),
            'tags': ({'variant': 0, 'type': 'TEXT', 'value': 'Trigger'},),
        }
        source = dict(self.values)
        source.update({
            'Scene1StartAddress': (0,), 'SceneCount': (1,),
            'SceneBucket': tuple(bytes((2, 0, 42, 2, 26)).ljust(232, b'\xff')),
        })
        self.client.values = {
            name: ' '.join('0x' + format(value, 'x') for value in values)
            for name, values in source.items()
        }
        plan = plan_native_parent_metadata(
            self.client.xml(), '//TEST/254/p/20', source,
            self.editor, self.operations)
        self.assertEqual(plan.cache.find(202, 42).levels, (2, 7))

    def test_missing_consumed_scene_trigger_does_not_invent_levels(self):
        source = dict(self.values)
        source.update({
            'Scene1StartAddress': (0,), 'SceneCount': (1,),
            'SceneBucket': tuple(bytes((2, 0, 42, 2, 26)).ljust(232, b'\xff')),
        })
        self.client.values = {
            name: ' '.join('0x' + format(value, 'x') for value in values)
            for name, values in source.items()
        }
        with self.assertRaisesRegex(ValueError, 'level creation'):
            plan_native_parent_metadata(
                self.client.xml(), '//TEST/254/p/20', source,
                self.editor, self.operations)

    def test_external_or_builtin_image_dependency_fails_closed(self):
        self.client.applications[56]['groups'][12] = {
            'oid': oid(120), 'tag': 'Lighting group', 'levels': (),
            'tags': ({'variant': 0, 'type': 'DYNAMIC', 'value': 'image.png'},),
        }
        source = dict(self.values)
        source.update({'Widget6WidgetType': (2,),
                       'Widget6WidgetByteValue1': (16,),
                       'Widget6WidgetByteValue6': (12,),
                       'Widget6WidgetByteValue13': (0,)})
        self.client.values = {
            name: ' '.join('0x' + format(value, 'x') for value in values)
            for name, values in source.items()
        }
        with self.assertRaisesRegex(ValueError, 'not derivable from DBGETXML'):
            plan_native_parent_metadata(
                self.client.xml(), '//TEST/254/p/20', source,
                self.editor, self.operations)

    def test_stale_pp_duplicate_metadata_and_secondary_ambiguity_are_rejected(self):
        stale = dict(self.values, ProximityLevel=(99,))
        with self.assertRaisesRegex(ValueError, 'PP snapshot differs'):
            plan_native_parent_metadata(
                self.client.xml(), '//TEST/254/p/20', stale,
                self.editor, self.operations)
        duplicate = self.client.xml().replace(
            '</Application><Application><OID>' + oid(202),
            '<Group><OID>' + oid(800) + '</OID><TagName>A</TagName><Address>1</Address></Group>'
            '<Group><OID>' + oid(801) + '</OID><TagName>B</TagName><Address>1</Address></Group>'
            '</Application><Application><OID>' + oid(202), 1)
        with self.assertRaisesRegex(ValueError, 'duplicate group'):
            plan_native_parent_metadata(
                duplicate, '//TEST/254/p/20', self.values,
                self.editor, self.operations)
        no_secondary = dict(self.values, SecondaryApplication=(255,))
        self.client.values['SecondaryApplication'] = '0xff'
        with self.assertRaisesRegex(EdltError, 'Secondary'):
            plan_native_parent_metadata(
                self.client.xml(), '//TEST/254/p/20', no_secondary,
                self.editor,
                (measurement(), lighting(application='secondary')))

    def manager(self):
        session = NativeSession(self.spec, self.client)
        programmer = FakeProgrammer(session)
        return NativeEdltParentTransaction(
            self.client, self.editor, programmer=programmer), session, programmer

    def test_native_success_creates_once_saves_once_and_verifies_reload(self):
        manager, session, programmer = self.manager()
        plan = manager.plan(
            '//TEST/254/p/20', operations=self.operations,
            exclusive_project=True)
        result = manager.apply(plan, backup_project='BACKUP').as_dict()
        self.assertTrue(result['complete'] and result['persistence_verified'])
        self.assertTrue(result['saved'])
        self.assertEqual(result['database_persistence'],
                         'verified-after-project-reload')
        self.assertTrue(result['pp_save_confirmed'])
        self.assertTrue(result['target_project_save_confirmed'])
        self.assertTrue(result['existing_metadata_preserved'])
        self.assertEqual(programmer.calls,
                         [('//TEST/254', '/db//TEST/254/p/20')])
        self.assertEqual(set(self.client.applications), {56, 202, 203})
        self.assertEqual(set(self.client.applications[56]['groups']), {12, 42})
        self.assertEqual(sum(command == 'PROJECT SAVE TEST'
                             for command in self.client.commands), 2)
        self.assertEqual(len(self.client.backups), 1)
        self.assertEqual(self.client.values['ProximityLevel'], '127')
        self.assertFalse(result['batch_atomic'])

    def test_pre_save_pp_failure_rolls_back_metadata_and_pp(self):
        manager, session, _ = self.manager()
        plan = manager.plan(
            '//TEST/254/p/20', operations=self.operations,
            exclusive_project=True)
        session.failure = 'ProximityLevel'
        with self.assertRaises(NativeEdltParentError) as caught:
            manager.apply(plan, backup_project='BACKUP')
        evidence = caught.exception.details['edlt_parent_metadata_evidence']
        self.assertTrue(evidence['rollback_attempted'])
        self.assertTrue(evidence['rollback_verified'])
        self.assertFalse(evidence['pp_save_attempted'])
        self.assertFalse(evidence['pp_state_uncertain'])
        self.assertEqual(set(self.client.applications), {56, 202})
        self.assertEqual(self.client.values, self.client.saved_values)

    def test_exact_stale_guard_stops_before_backup_or_mutation(self):
        manager, _session, _ = self.manager()
        plan = manager.plan(
            '//TEST/254/p/20', operations=self.operations,
            exclusive_project=True)
        self.client.applications[56]['tag'] = 'Changed concurrently'
        with self.assertRaises(NativeEdltParentError) as caught:
            manager.apply(plan, backup_project='BACKUP')
        evidence = caught.exception.details['edlt_parent_metadata_evidence']
        self.assertFalse(evidence['backup_created'])
        self.assertFalse(evidence['metadata_mutation_attempted'])
        self.assertFalse(evidence['pp_mutation_attempted'])
        self.assertFalse(evidence['saved'])
        self.assertEqual(evidence['database_persistence'], 'not-saved')
        self.assertFalse(any(command.startswith(('DBADD', 'PROJECT '))
                             for command in self.client.commands))

    def test_lost_pp_save_reply_is_partial_and_never_rolled_back(self):
        manager, session, _ = self.manager()
        plan = manager.plan(
            '//TEST/254/p/20', operations=self.operations,
            exclusive_project=True)
        session.save_error = RuntimeError('PP SAVE reply lost')
        with self.assertRaises(NativeEdltParentError) as caught:
            manager.apply(plan, backup_project='BACKUP')
        evidence = caught.exception.details['edlt_parent_metadata_evidence']
        self.assertTrue(evidence['pp_save_attempted'])
        self.assertFalse(evidence['pp_save_confirmed'])
        self.assertTrue(evidence['pp_save_outcome_uncertain'])
        self.assertFalse(evidence['rollback_attempted'])
        self.assertTrue(evidence['pp_state_uncertain'])
        self.assertTrue(evidence['database_state_uncertain'])
        self.assertTrue(evidence['partial_failure_possible'])
        self.assertEqual(evidence['automatic_retries'], 0)
        self.assertIn(203, self.client.applications)

    def test_interrupted_pp_save_attaches_conservative_evidence(self):
        manager, session, _ = self.manager()
        plan = manager.plan(
            '//TEST/254/p/20', operations=self.operations,
            exclusive_project=True)
        session.save_error = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt) as caught:
            manager.apply(plan, backup_project='BACKUP')
        evidence = caught.exception.edlt_parent_metadata_evidence
        self.assertTrue(evidence['pp_save_attempted'])
        self.assertFalse(evidence['pp_save_confirmed'])
        self.assertTrue(evidence['pp_state_uncertain'])
        self.assertTrue(evidence['database_state_uncertain'])
        self.assertFalse(evidence['rollback_attempted'])
        self.assertFalse(evidence['saved'])
        self.assertEqual(evidence['automatic_retries'], 0)

    def test_lost_project_save_reply_preserves_confirmed_pp_and_partial_boundary(self):
        manager, _session, _ = self.manager()
        plan = manager.plan(
            '//TEST/254/p/20', operations=self.operations,
            exclusive_project=True)

        def fail_second_save(command):
            if (command == 'PROJECT SAVE TEST'
                    and self.client.commands.count(command) == 2):
                return RuntimeError('PROJECT SAVE reply lost')
            return None

        self.client.failure = fail_second_save
        with self.assertRaises(NativeEdltParentError) as caught:
            manager.apply(plan, backup_project='BACKUP')
        evidence = caught.exception.details['edlt_parent_metadata_evidence']
        self.assertTrue(evidence['pp_save_confirmed'])
        self.assertTrue(evidence['target_project_save_attempted'])
        self.assertFalse(evidence['target_project_save_confirmed'])
        self.assertTrue(evidence['target_project_save_outcome_uncertain'])
        self.assertFalse(evidence['rollback_attempted'])
        self.assertFalse(evidence['pp_state_uncertain'])
        self.assertTrue(evidence['database_state_uncertain'])
        self.assertEqual(evidence['database_persistence'], 'uncertain')
        self.assertFalse(evidence['saved'])
        self.assertTrue(evidence['partial_failure_possible'])
        self.assertEqual(evidence['automatic_retries'], 0)

    def test_reload_rejects_an_unplanned_group_without_claiming_verified_save(self):
        manager, _session, _ = self.manager()
        plan = manager.plan(
            '//TEST/254/p/20', operations=self.operations,
            exclusive_project=True)

        def inject_after_save(command):
            if command == 'PROJECT LOAD TEST':
                self.client.saved_applications[56]['groups'][99] = {
                    'oid': oid(990), 'tag': 'Concurrent', 'levels': ()}
            return None

        self.client.failure = inject_after_save
        with self.assertRaises(NativeEdltParentError) as caught:
            manager.apply(plan, backup_project='BACKUP')
        evidence = caught.exception.details['edlt_parent_metadata_evidence']
        self.assertTrue(evidence['target_project_save_confirmed'])
        self.assertFalse(evidence['persistence_verified'])
        self.assertFalse(evidence['saved'])
        self.assertEqual(evidence['database_persistence'],
                         'save-confirmed-verification-incomplete')
        self.assertIn('inventory changed', evidence['error']['message'])

    def test_source_evidence_fixture_pins_original_methods_and_boundaries(self):
        document = json.loads(EVIDENCE.read_text())
        self.assertEqual(document['format'],
                         'cbus-edlt-parent-metadata-evidence-v1')
        self.assertEqual(document['profile']['toolkit'], '1.18.0.2754')
        methods = {row['method'] for row in document['original_methods']}
        self.assertIn('CBusNetwork.GetApplicationByAddress', methods)
        self.assertIn('CBusApplication.GetGroupByAddress', methods)
        self.assertIn('EDLTUnit.AfterLoadPPData', methods)
        self.assertFalse(document['evidence_boundaries'][
            'native_combined_transaction_executed'])
        self.assertFalse(document['evidence_boundaries']['physical_device_verified'])
        acceptance = json.loads(ACCEPTANCE.read_text())
        self.assertEqual(acceptance['format'],
                         'cbus-edlt-parent-metadata-acceptance-v1')
        self.assertTrue(acceptance['failure_semantics'][
            'pre_pp_save_failure_reload_rollback_verified'])
        self.assertFalse(acceptance['evidence'][
            'fresh_schneider_cgate_combined_transaction'])

    @unittest.skipUnless(
        os.environ.get('CBUS_EDLT_PARENT_METADATA_ACCEPTANCE') == '1'
        and os.environ.get('CBUS_EDLT_PARENT_METADATA_UNIT')
        and os.environ.get('CBUS_EDLT_PARENT_METADATA_BACKUP')
        and os.environ.get('CBUS_CGATE_TEST_HOST')
        and os.environ.get('CBUS_UNITSPEC_DIR'),
        'Set the explicit disposable closed-project native metadata acceptance environment')
    def test_optional_native_database_metadata_parent_transaction(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.unitspec import UnitSpecStore

        native_editor = EdltParentTransaction(
            UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR']).load('KEYGL5.xml'))
        host = os.environ['CBUS_CGATE_TEST_HOST']
        port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        with CGateClient(host, port, timeout=30) as native_client:
            manager = NativeEdltParentTransaction(native_client, native_editor)
            plan = manager.plan(
                os.environ['CBUS_EDLT_PARENT_METADATA_UNIT'],
                operations=self.operations, exclusive_project=True)
            result = manager.apply(
                plan, backup_project=os.environ[
                    'CBUS_EDLT_PARENT_METADATA_BACKUP']).as_dict()
        self.assertTrue(result['persistence_verified'])
        self.assertTrue(result['pp_save_confirmed'])
        self.assertTrue(result['target_project_save_confirmed'])
        self.assertFalse(result['physical_device_programmed'])


if __name__ == '__main__':
    unittest.main()
