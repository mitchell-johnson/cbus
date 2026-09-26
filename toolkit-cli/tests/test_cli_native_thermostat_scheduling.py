"""Public CLI boundary for native thermostat scheduling composition."""
import argparse
from copy import deepcopy
import unittest
from unittest.mock import Mock, patch

from cbus_toolkit import thermostat_schedule_cli as helper
from cbus_toolkit.cli import build_parser, run
from cbus_toolkit.native_thermostat_schedule import NativeScheduleError
from tests.test_cli_thermostat_schedule import Connection
from tests.test_native_thermostat_scheduling import CompositionClient, UNIT, RAW, group


def arguments(*extra):
    parser = argparse.ArgumentParser()
    parser.set_defaults(area='cgate', action='thermostat-schedule-compose',
                        host='127.0.0.1', port=None, tls=False, timeout=5)
    helper.compose_options(parser)
    return parser.parse_args([UNIT, '--exclusive-project', *extra])


class NativeThermostatSchedulingCLITests(unittest.TestCase):
    def invoke(self, args, client):
        context = Connection(client)
        factory = Mock(return_value=context)
        result = helper.native(args, factory, None)
        return result, context, factory

    def test_public_parser_exposes_composition_options(self):
        args = build_parser().parse_args([
            'cgate', 'thermostat-schedule-compose', UNIT, '--exclusive-project',
            '--policy', 'direct', '--application-name', 'Enable',
            '--group-name', 'Schedule', '--unused-name', 'Unused'])
        self.assertEqual(args.action, 'thermostat-schedule-compose')
        self.assertEqual(args.unit, UNIT)
        self.assertEqual((args.policy, args.application_name, args.group_name, args.unused_name),
                         ('direct', 'Enable', 'Schedule', 'Unused'))
        self.assertFalse(args.apply)

    def test_public_dispatch_routes_to_shared_native_boundary(self):
        args = build_parser().parse_args([
            'cgate', 'thermostat-schedule-compose', UNIT, '--exclusive-project'])
        expected = ({'format': 'sentinel'}, 0)
        with patch.object(helper, 'native', return_value=expected) as native:
            self.assertEqual(run(args), expected)
        native.assert_called_once()
        self.assertIs(native.call_args.args[0], args)

    def test_preview_reads_one_project_snapshot_without_mutation(self):
        client = CompositionClient(groups={})
        before = deepcopy(client.application)
        (result, code), context, factory = self.invoke(arguments(), client)
        self.assertEqual(code, 0)
        self.assertEqual(result['format'], 'cbus-native-thermostat-scheduling-plan-v1')
        self.assertEqual(result['created_group_addresses'], [12, 13, 14])
        self.assertEqual(set(result['created_level_addresses']), {'12', '13', '14'})
        self.assertTrue(result['mutation_required'])
        self.assertFalse(result['cli']['apply_requested'])
        self.assertEqual(client.application, before)
        self.assertTrue(all(command.startswith(('DBGETXML ', 'GET '))
                            for command in client.commands))
        self.assertEqual(client.commands.count('DBGETXML //TEST'), 1)
        self.assertEqual((context.enters, context.exits), (1, 1))
        factory.assert_called_once_with('127.0.0.1', 20023, timeout=5, ssl_context=None)

    def test_apply_composes_application_groups_and_levels_with_one_target_save(self):
        client = CompositionClient(application=False)
        original_raw = dict(client.raw)
        (result, code), context, _factory = self.invoke(
            arguments('--apply', '--backup-project', 'BACKUP'), client)
        self.assertEqual(code, 0)
        self.assertTrue(result['complete'] and result['persistence_verified'])
        self.assertTrue(result['unit_record_preserved'])
        self.assertEqual(result['target_project_save_count'], 1)
        self.assertEqual(client.raw, original_raw)
        self.assertEqual(set(client.application['groups']), {12, 13, 14})
        self.assertTrue(all(set(value['levels']) == set(range(1, 32))
                            for value in client.application['groups'].values()))
        self.assertEqual(sum(command == 'PROJECT SAVE TEST' for command in client.commands), 2)
        self.assertEqual(context.exits, 1)

    def test_request_validation_precedes_connection_construction(self):
        changes = (
            {'unit': '//TEST/254/4'}, {'unit': '//TEST/256/p/4'},
            {'exclusive_project': False}, {'exclusive_project': 1},
            {'policy': 'wrong'}, {'application_name': ''}, {'group_name': 'bad\nname'},
            {'unused_name': ''}, {'apply': 1}, {'backup_project': 'BACKUP'},
            {'apply': True, 'backup_project': 'test'}, {'host': ''}, {'port': True},
            {'timeout': float('nan')}, {'tls': 1}, {'action': 'other'},
        )
        for change in changes:
            with self.subTest(change=change):
                args = arguments()
                for name, value in change.items():
                    setattr(args, name, value)
                factory = Mock(side_effect=AssertionError('No I/O for invalid request'))
                with self.assertRaises(ValueError):
                    helper.native(args, factory, None)
                factory.assert_not_called()

    def test_complete_state_apply_is_read_only(self):
        complete = {}
        for address, action in ((12, 'Enable'), (13, 'Disable'), (14, 'Overrd')):
            complete[address] = group(address, {
                number: {'oid': '00000000-0000-0000-0000-'
                                + format(address * 256 + number, '012x'),
                         'value': number,
                         'tag': 'Sched ' + action + (' Zone:' if number in (1, 2, 4, 8, 16) else ' Zones:')
                                + ','.join(name for bit, name in ((1, 'unsw'), (2, '1'), (4, '2'),
                                                                 (8, '3'), (16, '4')) if number & bit),
                         'opaque': '<Meta>retained</Meta>'}
                for number in range(1, 32)})
        client = CompositionClient(groups=complete, raw=dict(RAW))
        (result, _), _context, _factory = self.invoke(arguments('--apply'), client)
        self.assertEqual(result['state'], 'already_present')
        self.assertFalse(result['target_mutation_attempted'])
        self.assertFalse(any(command.startswith(('PROJECT ', 'DBADD', 'DBSET'))
                             for command in client.commands))

    def test_lost_target_save_reply_is_exported_as_uncertain_without_retry(self):
        client = CompositionClient(groups={12: group(12)})
        seen = 0

        def lose(command):
            nonlocal seen
            if command == 'PROJECT SAVE TEST':
                seen += 1
                if seen == 2:
                    return TimeoutError('target save reply lost')
            return None

        client.after = lose
        args = arguments('--apply', '--backup-project', 'BACKUP')
        with self.assertRaises(NativeScheduleError) as caught:
            self.invoke(args, client)
        evidence = helper.error_payload(caught.exception, args)[helper.EVIDENCE]
        native = evidence['native_result']
        self.assertTrue(native['outcome_uncertain'])
        self.assertTrue(native['target_save_outcome_uncertain'])
        self.assertFalse(native['target_save_confirmed'])
        self.assertEqual(native['automatic_retries'], 0)
        self.assertEqual(client.commands.count('PROJECT SAVE TEST'), 2)


if __name__ == '__main__':
    unittest.main()
