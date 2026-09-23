"""Native scheduling: final state, stale plans and partial write evidence."""
from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch
from uuid import UUID
from xml.sax.saxutils import escape

from cbus_toolkit.addressing import _RUNTIME_FIELDS
from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.native_thermostat_schedule import NativeThermostatScheduleLevels, NativeScheduleError


PATH = '//TEST/254/203/1'


def oid(value):
    return str(UUID(int=value))


def reply(code=200, message='OK.'):
    line = str(code) + ' ' + message
    return CGateResponse((line,), line, code)


class FixtureClient:
    """A retained command peer with separate live/saved/backup state."""
    def __init__(self, levels=None):
        self.levels = deepcopy(levels or {})
        self.saved = deepcopy(self.levels)
        self.backups = {}
        self.commands = []
        self.failure = None
        self.after = None
        self.next_oid = 1000
        self.network_open = False
        self.materialized = False
        self.current_project = None
        self.opaque = '<Notes><Part>A</Part><Part>B</Part></Notes>'

    def xml(self):
        rows = []
        for address, value in self.levels.items():
            rows.append('<Level Value="' + str(value['value']) + '"><OID>' + value['oid'] + '</OID><Address>'
                        + str(address) + '</Address><TagName>' + escape(value['tag']) + '</TagName>'
                        + value.get('opaque', '') + ('<TagsDLT/>' if self.materialized else '') + '</Level>')
        return '<NetVar><OID>' + oid(1) + '</OID><TagName>Schedule</TagName><Address>1</Address>' + self.opaque + ''.join(rows) + '</NetVar>'

    def command(self, command):
        self.commands.append(command)
        if self.failure:
            result = self.failure(command)
            if isinstance(result, BaseException):
                raise result
            if result is not None:
                return result
        if command == 'DBGETXML //TEST':
            result = self.xml_reply('<Installation><Project><Network><Address>254</Address></Network></Project></Installation>')
        elif command == 'GET //TEST/254 *':
            values = {name: 'fixture' for name in _RUNTIME_FIELDS}
            values.update(InterfaceState='open' if self.network_open else 'closed', TargetInterfaceState='closed', SyncState='idle')
            lines = tuple('300' + (' ' if index == len(values)-1 else '-') + '//TEST/254: ' + key + '=' + value
                          for index, (key, value) in enumerate(values.items()))
            result = CGateResponse(lines, lines[-1], 300)
        elif command == 'DBGETXML ' + PATH:
            result = self.xml_reply(self.xml())
        elif command == 'PROJECT SAVE TEST':
            self.saved = deepcopy(self.levels); result = reply()
        elif command.startswith('PROJECT COPY TEST '):
            backup = command.split()[-1]
            if backup in self.backups:
                return reply(401, 'Already exists')
            self.backups[backup] = deepcopy(self.saved); result = reply()
        elif command == 'PROJECT CLOSE TEST':
            self.current_project = None
            result = reply()
        elif command == 'PROJECT USE TEST':
            self.current_project = 'TEST'; result = reply()
        elif command == 'PROJECT LOAD TEST':
            self.levels = deepcopy(self.saved); self.materialized = True; result = reply()
        elif command.startswith('DBADDSAFE ' + PATH + ' Level '):
            address, tag = command[len('DBADDSAFE ' + PATH + ' Level '):].split(' ', 1)
            address = int(address)
            if address in self.levels:
                return reply(401, 'Element address in use')
            self.next_oid += 1; identity = oid(self.next_oid)
            self.levels[address] = {'oid': identity, 'tag': tag, 'value': None}
            result = reply(301, 'OID=' + identity)
        elif command.startswith('DBGET !') and command.endswith('/OID'):
            if self.current_project != 'TEST': return reply(440, 'There is no tag database to perform this operation on')
            identity = command[len('DBGET !'):-4]
            if not any(value['oid'] == identity for value in self.levels.values()):
                return reply(401, 'Unknown OID')
            result = reply(342, '!' + identity + '/OID=' + identity)
        elif command.startswith('DBSETSAFE !'):
            if self.current_project != 'TEST': return reply(440, 'There is no tag database to perform this operation on')
            field_path, value = command[len('DBSETSAFE !'):].split(' ', 1)
            identity, field = field_path.split('/')
            target = next(level for level in self.levels.values() if level['oid'] == identity)
            if field == 'Value':
                target['value'] = int(value)
            elif field == 'TagName':
                target['tag'] = value
            else:
                raise AssertionError('Unapproved field ' + field)
            result = reply()
        else:
            raise AssertionError('Unapproved fixture command: ' + command)
        if self.after:
            error = self.after(command)
            if error is not None:
                raise error
        return result

    @staticmethod
    def xml_reply(value):
        return CGateResponse(('343-Begin XML snippet', '347-' + value, '344 End XML snippet'), '344 End XML snippet', 344)


def existing(addresses):
    return {value: {'oid': oid(value+20), 'value': 255-value, 'tag': 'Existing ' + str(value),
                    'opaque': '<Meta><Part>first</Part><Part>second</Part></Meta>'} for value in addresses}


class NativeThermostatScheduleTests(unittest.TestCase):
    def test_native_sequence_preserves_extra_addresses_values_and_metadata(self):
        original = existing((0, 1, 32, 255))
        client = FixtureClient(original); engine = NativeThermostatScheduleLevels(client)
        plan = engine.plan(PATH, 'Enable', exclusive_project=True)
        self.assertEqual(plan.created_addresses, tuple(range(2, 32)))
        result = engine.apply(plan, backup_project='BACKUP').as_dict()
        self.assertTrue(result['complete'] and result['persistence_verified'])
        self.assertEqual(client.backups['BACKUP'], original)
        self.assertEqual({address: client.levels[address] for address in original}, original)
        self.assertEqual(client.levels[31]['value'], 31)
        self.assertEqual(client.levels[31]['tag'], 'Sched Enable Zones:unsw,1,2,3,4')
        adds = [value for value in client.commands if value.startswith('DBADDSAFE')]
        self.assertEqual(len(adds), 30)
        self.assertTrue(adds[0].endswith('Level 2 Level 2'))
        self.assertLess(client.commands.index('PROJECT COPY TEST BACKUP'), client.commands.index(adds[0]))
        self.assertEqual(client.commands[-4], 'PROJECT LOAD TEST')
        result['levels'].clear()
        self.assertEqual(len(engine.last_result.as_dict()['levels']), 30)

    def test_complete_levels_make_no_backup_or_write_and_attempt_cannot_replay(self):
        client = FixtureClient(existing(range(32))); engine = NativeThermostatScheduleLevels(client)
        plan = engine.plan(PATH, 'Disable', exclusive_project=True)
        result = engine.apply(plan).as_dict()
        self.assertEqual(result['state'], 'already_present')
        self.assertFalse(result['persistence_verified'])
        self.assertFalse(any(command.startswith(('PROJECT ', 'DBSET', 'DBADD')) for command in client.commands))
        count = len(client.commands)
        with self.assertRaises(NativeScheduleError):
            engine.apply(plan)
        self.assertEqual(len(client.commands), count)

    def test_invalid_request_is_rejected_before_io(self):
        for path, action, exclusive in ((PATH, None, True), (PATH, 'Enable', False), ('//TEST/254/56/1', 'Enable', True),
                                         ('//TEST/254/203/255', 'Enable', True), (PATH+'\nSHUTDOWN', 'Enable', True)):
            client = FixtureClient(); engine = NativeThermostatScheduleLevels(client)
            with self.assertRaises(NativeScheduleError):
                engine.plan(path, action, exclusive_project=exclusive)
            self.assertEqual(client.commands, [])

    def test_stale_plan_and_open_network_stop_before_backup(self):
        for mutation in ('level', 'network'):
            client = FixtureClient(existing((1,))); engine = NativeThermostatScheduleLevels(client)
            plan = engine.plan(PATH, 'Enable', exclusive_project=True)
            if mutation == 'level': client.levels[1]['value'] = 7
            else: client.network_open = True
            with self.assertRaises(NativeScheduleError):
                engine.apply(plan)
            self.assertFalse(any(command.startswith(('PROJECT ', 'DBSET', 'DBADD')) for command in client.commands))

    def test_foreign_replaced_and_mutated_plans_have_no_io(self):
        client = FixtureClient(); engine = NativeThermostatScheduleLevels(client)
        plan = engine.plan(PATH, 'Enable', exclusive_project=True)
        for candidate in (replace(plan), plan):
            if candidate is plan: object.__setattr__(plan, 'action', 'Disable')
            count = len(client.commands)
            with self.assertRaises(NativeScheduleError): engine.apply(candidate)
            self.assertEqual(len(client.commands), count)

    def test_copy_rejection_leaves_destination_unchanged(self):
        client = FixtureClient(); client.backups['BACKUP'] = {'previous': 'data'}
        engine = NativeThermostatScheduleLevels(client)
        plan = engine.plan(PATH, 'Enable', exclusive_project=True)
        with self.assertRaises(NativeScheduleError): engine.apply(plan, backup_project='BACKUP')
        result = engine.last_result.as_dict()
        self.assertFalse(result['backup_created'] or result['target_mutation_attempted'])
        self.assertEqual(client.backups['BACKUP'], {'previous': 'data'})
        self.assertEqual(client.levels, {})

    def test_lost_value_reply_retains_oid_and_uncertain_partial_state(self):
        client = FixtureClient(); engine = NativeThermostatScheduleLevels(client)
        plan = engine.plan(PATH, 'Overrd', exclusive_project=True)
        first = OSError('reply lost after applied value')
        client.after = lambda command: first if command.startswith('DBSETSAFE') and '/Value ' in command else None
        with self.assertRaises(NativeScheduleError) as caught: engine.apply(plan, backup_project='BACKUP')
        self.assertIs(caught.exception.cause, first)
        result = engine.last_result.as_dict(); phase = result['levels'][0]
        self.assertEqual(result['state'], 'uncertain')
        self.assertTrue(result['backup_created'] and phase['created'])
        self.assertFalse(phase['value_confirmed'] or phase['tag_confirmed'])
        self.assertEqual(client.levels[1]['value'], 1)
        self.assertEqual(client.levels[1]['tag'], 'Level 1')
        self.assertTrue(client.commands[-1].endswith('/Value 1'))

    def test_post_save_interrupt_keeps_confirmed_save_and_exact_first_error(self):
        for error in (KeyboardInterrupt('stop'), SystemExit(27)):
            client = FixtureClient(); engine = NativeThermostatScheduleLevels(client)
            plan = engine.plan(PATH, 'Enable', exclusive_project=True)
            client.failure = lambda command: error if command == 'PROJECT LOAD TEST' else None
            with self.assertRaises(type(error)) as caught: engine.apply(plan)
            self.assertIs(caught.exception, error)
            result = engine.last_result.as_dict()
            self.assertTrue(result['target_save_confirmed'])
            self.assertFalse(result['persistence_verified'] or result['complete'])
            self.assertEqual(client.commands[-1], 'PROJECT LOAD TEST')

    def test_metadata_reordering_inside_an_opaque_field_is_detected(self):
        client = FixtureClient(existing((1,))); engine = NativeThermostatScheduleLevels(client)
        plan = engine.plan(PATH, 'Enable', exclusive_project=True)
        def change(command):
            if command == 'PROJECT LOAD TEST':
                client.levels[1]['opaque'] = '<Meta><Part>second</Part><Part>first</Part></Meta>'
        client.after = change
        with self.assertRaises(NativeScheduleError): engine.apply(plan)
        result = engine.last_result.as_dict()
        self.assertTrue(result['target_save_confirmed'])
        self.assertFalse(result['persistence_verified'])

    def test_rejected_creation_does_not_continue_to_value_or_tag(self):
        client = FixtureClient(); engine = NativeThermostatScheduleLevels(client)
        plan = engine.plan(PATH, 'Enable', exclusive_project=True)
        client.failure = lambda command: reply(600, 'Confirmation required') if command.startswith('DBADDSAFE') else None
        with self.assertRaises(NativeScheduleError): engine.apply(plan)
        result = engine.last_result.as_dict()
        self.assertFalse(result['levels'][0]['created'])
        self.assertFalse(any(command.startswith('DBSET') for command in client.commands))

    def test_opaque_whitespace_and_top_level_order_are_preserved(self):
        for before, after in (('<Meta> </Meta>', '<Meta>  </Meta>'),
                              ('<First/><Second/>', '<Second/><First/>')):
            client = FixtureClient(existing((1,)))
            client.levels[1]['opaque'] = before
            engine = NativeThermostatScheduleLevels(client)
            plan = engine.plan(PATH, 'Enable', exclusive_project=True)
            def change(command):
                if command == 'PROJECT LOAD TEST': client.levels[1]['opaque'] = after
            client.after = change
            with self.assertRaises(NativeScheduleError): engine.apply(plan)
            self.assertFalse(engine.last_result.as_dict()['persistence_verified'])

    def test_evidence_failure_does_not_replace_first_interruption_or_saved_phase(self):
        for first in (KeyboardInterrupt('first'), SystemExit(27)):
            client = FixtureClient(); engine = NativeThermostatScheduleLevels(client)
            plan = engine.plan(PATH, 'Enable', exclusive_project=True)
            client.failure = lambda command: first if command == 'PROJECT LOAD TEST' else None
            secondary = SystemExit(39)
            with patch.object(engine, '_finish', side_effect=secondary):
                with self.assertRaises(type(first)) as caught: engine.apply(plan)
            self.assertIs(caught.exception, first)
            self.assertIs(engine.last_error, first)
            self.assertEqual(engine.last_evidence_errors, (secondary,))
            self.assertTrue(engine.last_result.as_dict()['target_save_confirmed'])
            self.assertFalse(engine.last_result.as_dict()['persistence_verified'])


if __name__ == '__main__':
    unittest.main()
