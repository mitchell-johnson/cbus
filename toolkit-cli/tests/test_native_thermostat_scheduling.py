"""Native unit/application/group/level thermostat composition."""
from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch
from uuid import UUID
from xml.sax.saxutils import escape

from cbus_toolkit.addressing import _RUNTIME_FIELDS
from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.native_thermostat_schedule import NativeScheduleError
from cbus_toolkit.native_thermostat_scheduling import NativeThermostatScheduling


UNIT = '//TEST/254/p/4'
RAW = {'RemoteScheduleOnGroup': 12, 'RemoteScheduleOffGroup': 13,
       'RemoteScheduleOverrideGroup': 14, 'RemoteScheduleEnable': 0,
       'EvapProgramEnabled': 1, 'NonEvapProgramEnabled': 0}


def oid(value):
    return str(UUID(int=value))


def reply(code=200, message='OK.'):
    line = str(code) + ' ' + message
    return CGateResponse((line,), line, code)


class CompositionClient:
    def __init__(self, *, application=True, groups=None, raw=None):
        self.raw = dict(RAW if raw is None else raw)
        self.other_parameter = '0x2a'
        self.project_address = 'TEST'
        self.project_note = 'retained project data'
        self.other_application = {'oid': oid(11), 'tag': 'Lighting',
                                  'note': 'retained application data'}
        self.application = ({'oid': oid(10), 'tag': 'Enable Control',
                             'groups': deepcopy(groups or {})} if application else None)
        self.saved = deepcopy(self.application)
        self.backups = {}
        self.commands = []
        self.current_project = 'TEST'
        self.network_open = False
        self.materialized = False
        self.unit_type = 'PC_TSA'
        self.next_oid = 1000
        self.failure = None
        self.after = None

    def _new_oid(self):
        self.next_oid += 1
        return oid(self.next_oid)

    def _level(self, address, value):
        opaque = value.get('opaque', '')
        materialized = '<TagsDLT/>' if self.materialized else ''
        return ('<Level Value="' + str(value['value']) + '"><OID>' + value['oid']
                + '</OID><Address>' + str(address) + '</Address><TagName>'
                + escape(value['tag']) + '</TagName>' + opaque + materialized + '</Level>')

    def xml(self):
        application = ('<Application><OID>' + self.other_application['oid']
            + '</OID><TagName>' + escape(self.other_application['tag'])
            + '</TagName><Address>56</Address><Description>'
            + escape(self.other_application['note']) + '</Description></Application>')
        if self.application is not None:
            groups = []
            for address, group in self.application['groups'].items():
                levels = ''.join(self._level(number, value)
                                 for number, value in group['levels'].items())
                groups.append('<NetVar><OID>' + group['oid'] + '</OID><TagName>'
                    + escape(group['tag']) + '</TagName><Address>' + str(address)
                    + '</Address><Notes>retained</Notes>' + levels + '</NetVar>')
            application += ('<Application><OID>' + self.application['oid']
                + '</OID><TagName>' + escape(self.application['tag'])
                + '</TagName><Address>203</Address><Description>retained</Description>'
                + ''.join(groups) + '</Application>')
        pp = ''.join('<PP Name="' + name + '" Value="0x' + format(value, 'x') + '"/>'
                     for name, value in self.raw.items())
        pp += '<PP Name="OtherParameter" Value="' + self.other_parameter + '"/>'
        return ('<Installation><Project><Address>' + escape(self.project_address)
                + '</Address><ProjectNote>' + escape(self.project_note)
                + '</ProjectNote><Network><Address>254</Address>'
                + application + '<Unit><OID>' + oid(4) + '</OID><TagName>Thermostat</TagName>'
                '<Address>4</Address><UnitType>' + self.unit_type + '</UnitType><FirmwareVersion>4.6.00</FirmwareVersion>'
                + pp + '<CatalogNumber>5070THP,BK</CatalogNumber></Unit></Network></Project></Installation>')

    @staticmethod
    def xml_reply(value):
        lines = ('343-Begin XML snippet', '347-' + value, '344 End XML snippet')
        return CGateResponse(lines, lines[-1], 344)

    def _find_oid(self, identity):
        if self.other_application['oid'] == identity:
            return True
        if self.application and self.application['oid'] == identity:
            return True
        for group in (self.application or {}).get('groups', {}).values():
            if group['oid'] == identity:
                return True
            if any(level['oid'] == identity for level in group['levels'].values()):
                return True
        return False

    def command(self, command):
        self.commands.append(command)
        if self.failure:
            value = self.failure(command)
            if isinstance(value, BaseException):
                raise value
            if value is not None:
                return value
        if command == 'DBGETXML //TEST':
            result = self.xml_reply(self.xml())
        elif command == 'GET //TEST/254 *':
            values = {name: 'fixture' for name in _RUNTIME_FIELDS}
            values.update(InterfaceState='open' if self.network_open else 'closed',
                          TargetInterfaceState='closed', SyncState='idle')
            lines = tuple('300' + (' ' if index == len(values) - 1 else '-')
                          + '//TEST/254: ' + name + '=' + value
                          for index, (name, value) in enumerate(values.items()))
            result = CGateResponse(lines, lines[-1], 300)
        elif command == 'PROJECT SAVE TEST':
            self.saved = deepcopy(self.application); result = reply()
        elif command.startswith('PROJECT COPY TEST '):
            name = command.rsplit(' ', 1)[1]
            if name in self.backups:
                result = reply(401, 'Already exists')
            else:
                self.backups[name] = deepcopy(self.saved); result = reply()
        elif command == 'PROJECT USE TEST':
            self.current_project = 'TEST'; result = reply()
        elif command == 'PROJECT CLOSE TEST':
            self.current_project = None; result = reply()
        elif command == 'PROJECT LOAD TEST':
            self.application = deepcopy(self.saved); self.current_project = 'TEST'
            self.materialized = True; result = reply()
        elif command.startswith('DBADDSAFE //TEST/254 Application 203 '):
            if self.application is not None:
                result = reply(401, 'Element address in use')
            else:
                identity = self._new_oid()
                self.application = {'oid': identity, 'tag': command.split(' ', 4)[4], 'groups': {}}
                result = reply(301, 'OID=' + identity)
        elif command.startswith('DBADDSAFE //TEST/254/203 NetVar '):
            address, tag = command[len('DBADDSAFE //TEST/254/203 NetVar '):].split(' ', 1)
            address = int(address); identity = self._new_oid()
            self.application['groups'][address] = {'oid': identity, 'tag': tag, 'levels': {}}
            result = reply(301, 'OID=' + identity)
        elif command.startswith('DBADDSAFE //TEST/254/203/') and ' Level ' in command:
            prefix, values = command.split(' Level ', 1)
            group_address = int(prefix.rsplit('/', 1)[1])
            address, tag = values.split(' ', 1); address = int(address)
            levels = self.application['groups'][group_address]['levels']
            if address in levels:
                result = reply(401, 'Element address in use')
            else:
                identity = self._new_oid()
                levels[address] = {'oid': identity, 'value': None, 'tag': tag}
                result = reply(301, 'OID=' + identity)
        elif command.startswith('DBGET !') and command.endswith('/OID'):
            identity = command[len('DBGET !'):-4]
            result = (reply(342, '!' + identity + '/OID=' + identity)
                      if self._find_oid(identity) else reply(401, 'Unknown OID'))
        elif command.startswith('DBSETSAFE !'):
            field_path, value = command[len('DBSETSAFE !'):].split(' ', 1)
            identity, field = field_path.split('/')
            level = next(level for group in self.application['groups'].values()
                         for level in group['levels'].values() if level['oid'] == identity)
            if field == 'Value':
                level['value'] = int(value)
            elif field == 'TagName':
                level['tag'] = value
            else:
                raise AssertionError('Unexpected field ' + field)
            result = reply()
        else:
            raise AssertionError('Unexpected command: ' + command)
        if self.after:
            failure = self.after(command)
            if failure is not None:
                raise failure
        return result


def group(address, levels=None, *, identity=None, tag=None):
    return {'oid': identity or oid(100 + address), 'tag': tag or 'Group ' + str(address),
            'levels': deepcopy(levels or {})}


def level(address, *, value=None, tag=None, identity=None):
    return {'oid': identity or oid(200 + address), 'value': address if value is None else value,
            'tag': tag or 'Existing ' + str(address),
            'opaque': '<Meta>retained</Meta>'}


class NativeThermostatSchedulingTests(unittest.TestCase):
    def test_disabled_missing_application_creates_only_application_and_saves_once(self):
        raw = dict(RAW, EvapProgramEnabled=0, NonEvapProgramEnabled=0)
        client = CompositionClient(application=False, raw=raw)
        manager = NativeThermostatScheduling(client)
        plan = manager.plan(UNIT, exclusive_project=True)
        document = plan.as_dict()
        self.assertTrue(document['application_created'])
        self.assertEqual(document['created_group_addresses'], [])
        self.assertEqual(document['created_level_addresses'], {})
        result = manager.apply(plan, backup_project='BACKUP').as_dict()
        self.assertTrue(result['complete'] and result['persistence_verified'])
        self.assertTrue(result['unit_record_preserved'])
        self.assertEqual(result['target_project_save_count'], 1)
        self.assertEqual(client.raw, raw)
        self.assertEqual(client.other_parameter, '0x2a')
        self.assertEqual(client.application['groups'], {})
        self.assertEqual(sum(c == 'PROJECT SAVE TEST' for c in client.commands), 2)
        self.assertIsNone(client.backups['BACKUP'])

    def test_three_groups_and_all_missing_levels_compose_into_one_target_save(self):
        client = CompositionClient(groups={12: group(12, {1: level(1, value=205)})})
        before = deepcopy(client.application)
        manager = NativeThermostatScheduling(client)
        plan = manager.plan(UNIT, exclusive_project=True)
        document = plan.as_dict()
        self.assertEqual(document['created_group_addresses'], [13, 14])
        self.assertEqual(document['created_level_addresses']['12'], list(range(2, 32)))
        self.assertEqual(document['created_level_addresses']['13'], list(range(1, 32)))
        self.assertEqual(document['created_level_addresses']['14'], list(range(1, 32)))
        self.assertEqual(document['planned_creations']['application'], None)
        self.assertEqual([row['address'] for row in
                          document['planned_creations']['groups']], [13, 14])
        self.assertEqual(len(document['planned_creations']['levels']), 92)
        self.assertTrue(document['preserved_project_sha256'])
        result = manager.apply(plan, backup_project='BACKUP').as_dict()
        self.assertTrue(result['persistence_verified'])
        self.assertTrue(result['unknown_project_data_preserved'])
        self.assertEqual(result['target_project_save_count'], 1)
        self.assertEqual(client.backups['BACKUP'], before)
        self.assertEqual(client.application['groups'][12]['levels'][1], before['groups'][12]['levels'][1])
        self.assertEqual(set(client.application['groups']), {12, 13, 14})
        for address, action in ((12, 'Enable'), (13, 'Disable'), (14, 'Overrd')):
            levels = client.application['groups'][address]['levels']
            self.assertEqual(set(levels), set(range(1, 32)))
            self.assertEqual(levels[31]['tag'], 'Sched ' + action + ' Zones:unsw,1,2,3,4')
        self.assertEqual(sum(c == 'PROJECT SAVE TEST' for c in client.commands), 2)

    def test_shared_group_is_created_once_and_roles_are_composed_once(self):
        raw = dict(RAW, RemoteScheduleOffGroup=12, RemoteScheduleOverrideGroup=12)
        client = CompositionClient(groups={}, raw=raw)
        plan = NativeThermostatScheduling(client).plan(UNIT, exclusive_project=True)
        self.assertEqual(plan.as_dict()['created_group_addresses'], [12])
        self.assertEqual(plan.as_dict()['created_level_addresses']['12'], list(range(1, 32)))
        self.assertEqual(len(plan.expected_groups), 1)

    def test_complete_existing_state_is_a_read_only_noop(self):
        groups = {}
        for address, action in ((12, 'Enable'), (13, 'Disable'), (14, 'Overrd')):
            groups[address] = group(address, {number: level(number,
                identity=oid(address * 256 + number),
                tag='Sched ' + action + (' Zone:' if number in (1, 2, 4, 8, 16) else ' Zones:')
                + ','.join(name for bit, name in ((1, 'unsw'), (2, '1'), (4, '2'), (8, '3'), (16, '4'))
                           if number & bit)) for number in range(1, 32)})
        client = CompositionClient(groups=groups)
        manager = NativeThermostatScheduling(client)
        plan = manager.plan(UNIT, exclusive_project=True)
        self.assertFalse(plan.mutation_required)
        before = list(client.commands)
        result = manager.apply(plan).as_dict()
        self.assertEqual(result['state'], 'already_present')
        self.assertFalse(result['target_mutation_attempted'])
        self.assertFalse(any(command.startswith(('PROJECT ', 'DBADD', 'DBSET'))
                             for command in client.commands[len(before):]))

    def test_stale_unit_application_or_unrelated_project_stops_before_backup(self):
        for mutation in ('unit', 'application', 'project', 'other-application', 'network'):
            with self.subTest(mutation=mutation):
                client = CompositionClient(groups={12: group(12)})
                manager = NativeThermostatScheduling(client)
                plan = manager.plan(UNIT, exclusive_project=True)
                if mutation == 'unit':
                    client.other_parameter = '0x2b'
                elif mutation == 'application':
                    client.application['tag'] = 'External edit'
                elif mutation == 'project':
                    client.project_note = 'External project edit'
                elif mutation == 'other-application':
                    client.other_application['note'] = 'External application edit'
                else:
                    client.network_open = True
                with self.assertRaises(NativeScheduleError):
                    manager.apply(plan)
                self.assertFalse(any(command.startswith('PROJECT SAVE') for command in client.commands))

    def test_lost_level_value_reply_retains_backup_and_uncertain_state(self):
        client = CompositionClient(groups={12: group(12)})
        manager = NativeThermostatScheduling(client)
        plan = manager.plan(UNIT, exclusive_project=True)
        first = OSError('lost value reply')
        client.after = lambda command: first if command.startswith('DBSETSAFE !') and '/Value ' in command else None
        with self.assertRaises(NativeScheduleError) as caught:
            manager.apply(plan, backup_project='BACKUP')
        self.assertIs(caught.exception.cause, first)
        result = manager.last_result.as_dict()
        self.assertTrue(result['backup_created'] and result['target_mutation_attempted'])
        self.assertFalse(result['target_save_attempted'] or result['persistence_verified'])
        self.assertEqual(result['state'], 'uncertain')
        self.assertTrue(result['outcome_uncertain'])
        self.assertEqual(result['uncertain_commands'], [client.commands[-1]])
        self.assertEqual(client.commands.count(client.commands[-1]), 1)
        self.assertTrue(result['levels'][0]['created'])
        self.assertFalse(result['levels'][0]['value_confirmed'])

    def test_lost_backup_or_target_save_reply_is_explicitly_uncertain_without_retry(self):
        for phase in ('source-save', 'backup-copy', 'target-save'):
            with self.subTest(phase=phase):
                client = CompositionClient(groups={12: group(12)})
                manager = NativeThermostatScheduling(client)
                plan = manager.plan(UNIT, exclusive_project=True)
                seen = 0

                def lose(command):
                    nonlocal seen
                    if command == 'PROJECT SAVE TEST':
                        seen += 1
                        if ((phase == 'source-save' and seen == 1)
                                or (phase == 'target-save' and seen == 2)):
                            return OSError('lost save reply')
                    if (phase == 'backup-copy'
                            and command == 'PROJECT COPY TEST BACKUP'):
                        return OSError('lost backup copy reply')
                    return None

                client.after = lose
                with self.assertRaises(NativeScheduleError):
                    manager.apply(plan, backup_project='BACKUP')
                result = manager.last_result.as_dict()
                self.assertTrue(result['outcome_uncertain'])
                self.assertEqual(result['automatic_retries'], 0)
                self.assertEqual(client.commands.count('PROJECT SAVE TEST'),
                                 2 if phase == 'target-save' else 1)
                self.assertEqual(client.commands.count(
                    'PROJECT COPY TEST BACKUP'),
                    0 if phase == 'source-save' else 1)
                self.assertEqual(result['backup_source_save_outcome_uncertain'],
                                 phase == 'source-save')
                self.assertEqual(result['backup_copy_outcome_uncertain'],
                                 phase == 'backup-copy')
                self.assertEqual(result['target_save_outcome_uncertain'],
                                 phase == 'target-save')

    def test_reload_rejects_unrelated_project_data_change_after_confirmed_save(self):
        client = CompositionClient(groups={12: group(12)})
        manager = NativeThermostatScheduling(client)
        plan = manager.plan(UNIT, exclusive_project=True)

        def change(command):
            if command == 'PROJECT LOAD TEST':
                client.other_application['note'] = 'Unexpected save side effect'
            return None

        client.after = change
        with self.assertRaises(NativeScheduleError):
            manager.apply(plan, backup_project='BACKUP')
        result = manager.last_result.as_dict()
        self.assertTrue(result['target_save_confirmed'])
        self.assertFalse(result['persistence_verified'])
        self.assertFalse(result['outcome_uncertain'])
        self.assertNotIn('unknown_project_data_preserved', result)

    def test_ambiguous_project_identity_or_object_ids_stop_during_preview(self):
        for mutation in ('project', 'oid'):
            with self.subTest(mutation=mutation):
                client = CompositionClient(groups={12: group(12)})
                if mutation == 'project':
                    client.project_address = 'OTHER'
                else:
                    client.other_application['oid'] = oid(4)
                with self.assertRaises(NativeScheduleError):
                    NativeThermostatScheduling(client).plan(
                        UNIT, exclusive_project=True)
                self.assertFalse(any(command.startswith(
                    ('PROJECT SAVE', 'DBADD', 'DBSET'))
                    for command in client.commands))

    def test_invalid_inputs_and_forged_plan_have_no_mutation(self):
        for unit, exclusive, policy, name in (
                (UNIT, False, 'button', 'Enable Control'),
                ('//TEST/256/p/4', True, 'button', 'Enable Control'),
                (UNIT, True, 'wrong', 'Enable Control'),
                (UNIT, True, 'button', 'bad\nname')):
            client = CompositionClient(); manager = NativeThermostatScheduling(client)
            with self.assertRaises(NativeScheduleError):
                manager.plan(unit, exclusive_project=exclusive, policy=policy,
                             application_name=name)
            self.assertFalse(any(command.startswith(('PROJECT SAVE', 'DBADD', 'DBSET'))
                                 for command in client.commands))
        client = CompositionClient(); client.unit_type = 'KEY4'
        with self.assertRaises(NativeScheduleError):
            NativeThermostatScheduling(client).plan(UNIT, exclusive_project=True)
        self.assertFalse(any(command.startswith(('PROJECT SAVE', 'DBADD', 'DBSET'))
                             for command in client.commands))
        client = CompositionClient(); manager = NativeThermostatScheduling(client)
        plan = manager.plan(UNIT, exclusive_project=True)
        count = len(client.commands)
        with self.assertRaises(NativeScheduleError):
            manager.apply(replace(plan))
        self.assertEqual(len(client.commands), count)

    def test_first_interrupt_survives_evidence_failure(self):
        client = CompositionClient(groups={12: group(12)})
        manager = NativeThermostatScheduling(client)
        plan = manager.plan(UNIT, exclusive_project=True)
        first = KeyboardInterrupt('stop')
        client.failure = lambda command: first if command == 'PROJECT LOAD TEST' else None
        secondary = SystemExit('evidence failed')
        with patch.object(manager, '_finish', side_effect=secondary):
            with self.assertRaises(KeyboardInterrupt) as caught:
                manager.apply(plan)
        self.assertIs(caught.exception, first)
        self.assertTrue(manager.last_result.as_dict()['target_save_confirmed'])
        self.assertEqual(manager.last_evidence_errors, (secondary,))


if __name__ == '__main__':
    unittest.main()
