"""Scheduling CLI policy using the real coordinator and an owned command peer."""
import argparse
from copy import deepcopy
from contextlib import redirect_stderr
import io
import json
import unittest
from unittest.mock import Mock, patch

from cbus_toolkit import thermostat_schedule_cli as helper
from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.native_thermostat_schedule import NativeScheduleError, NativeScheduleResult
from tests.test_native_thermostat_schedule import FixtureClient, PATH, existing, reply


def arguments(*extra):
    parser = argparse.ArgumentParser()
    parser.set_defaults(area='cgate', action='thermostat-schedule-levels', host='127.0.0.1',
                        port=None, tls=False, timeout=5)
    helper.options(parser)
    return parser.parse_args([PATH, '--action', 'Enable', '--exclusive-project', *extra])


class Connection:
    def __init__(self, client, *, enter_error=None, exit_error=None, suppress=False):
        self.client, self.enter_error, self.exit_error = client, enter_error, exit_error
        self.suppress = suppress
        self.enters = self.exits = 0
        self.exit_primary = None

    def __enter__(self):
        self.enters += 1
        if self.enter_error is not None:
            raise self.enter_error
        return self.client

    def __exit__(self, typ, error, trace):
        self.exits += 1
        self.exit_primary = error
        if self.exit_error is not None:
            raise self.exit_error
        return self.suppress


class RefusedEvidence(KeyboardInterrupt):
    def __setattr__(self, name, value):
        if name.endswith('_evidence'):
            raise SystemExit('attachment refused')
        super().__setattr__(name, value)

    def __getattribute__(self, name):
        if name.endswith('_evidence'):
            raise SystemExit('getter refused')
        return super().__getattribute__(name)


class ThermostatScheduleCLITests(unittest.TestCase):
    def invoke(self, args, client, **kwargs):
        context = Connection(client, **kwargs)
        factory = Mock(return_value=context)
        result = helper.native(args, factory, None)
        return result, context, factory

    def test_options_keep_dispatch_action_and_require_exact_schedule_action(self):
        args = arguments('--action', 'Overrd')
        self.assertEqual(args.action, 'thermostat-schedule-levels')
        self.assertEqual(args.schedule_action, 'Overrd')
        self.assertFalse(args.apply)
        parser = argparse.ArgumentParser()
        helper.options(parser)
        for argv in ([PATH], [PATH, '--action', 'Override']):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                parser.parse_args(argv)
            self.assertEqual(caught.exception.code, 2)

    def test_all_request_validation_precedes_factory_or_connection(self):
        changes = (
            {'group': '//TEST/254/56/1'}, {'group': '//TEST/254/203/255'},
            {'group': PATH+'\nPROJECT DELETE TEST'}, {'group': '//TEST/0254/203/1'},
            {'schedule_action': None}, {'schedule_action': 'Override'},
            {'exclusive_project': False}, {'exclusive_project': 1}, {'apply': 1},
            {'backup_project': 'BACKUP'}, {'apply': True, 'backup_project': 'test'},
            {'apply': True, 'backup_project': 'TOO_LONG_NAME'}, {'apply': True, 'backup_project': 123},
            {'host': ''}, {'port': 0}, {'port': True}, {'timeout': float('nan')},
            {'timeout': True}, {'timeout': 0}, {'tls': 1}, {'action': 'other'},
        )
        for change in changes:
            with self.subTest(change=change):
                args = arguments()
                for name, value in change.items(): setattr(args, name, value)
                factory = Mock(side_effect=AssertionError('No I/O for invalid requests'))
                with self.assertRaises(ValueError): helper.native(args, factory, None)
                factory.assert_not_called()

    def test_default_preview_uses_read_commands_and_preserves_existing_levels(self):
        for action, tls, port in (('Enable', False, 20023), ('Disable', True, 20123), ('Overrd', False, 23456)):
            args = arguments('--action', action)
            args.tls = tls
            if port == 23456: args.port = port
            client = FixtureClient(existing((0, 1, 32, 255)))
            before = deepcopy(client.levels)
            context = Connection(client); factory = Mock(return_value=context); ssl = object()
            result, code = helper.native(args, factory, ssl)
            self.assertEqual(code, 0)
            self.assertEqual(result['format'], 'cbus-native-thermostat-schedule-plan-v1')
            self.assertEqual(result['action'], action)
            self.assertEqual(result['created_addresses'], list(range(2, 32)))
            self.assertFalse(result['native_mutation_performed'] or result['cli']['apply_requested'])
            self.assertTrue(result['cli']['complete'])
            self.assertEqual(client.levels, before)
            self.assertEqual(client.backups, {})
            self.assertTrue(all(c.startswith(('DBGETXML ', 'GET ')) for c in client.commands))
            self.assertEqual((context.enters, context.exits), (1, 1))
            factory.assert_called_once_with('127.0.0.1', port, timeout=5, ssl_context=ssl)

    def test_explicit_apply_backups_and_preserves_independent_saved_state(self):
        initial = existing((0, 1, 32, 255))
        client = FixtureClient(initial)
        (result, code), context, factory = self.invoke(arguments('--apply', '--backup-project', 'BACKUP'), client)
        self.assertEqual(code, 0)
        self.assertTrue(result['complete'] and result['persistence_verified'])
        self.assertTrue(result['backup_source_save_confirmed'] and result['target_save_confirmed'])
        self.assertTrue(result['cli']['apply_requested'] and result['cli']['connection_exit_completed'])
        self.assertEqual(client.backups['BACKUP'], initial)
        self.assertEqual(client.levels, client.saved)
        self.assertEqual({address: client.saved[address] for address in initial}, initial)
        self.assertEqual(client.saved[31]['tag'], 'Sched Enable Zones:unsw,1,2,3,4')
        self.assertEqual(len([c for c in client.commands if c.startswith('DBADDSAFE ')]), 30)
        self.assertEqual((context.enters, context.exits, factory.call_count), (1, 1, 1))

    def test_complete_existing_group_apply_reports_no_new_persistence(self):
        client = FixtureClient(existing(range(32)))
        (result, _), context, _ = self.invoke(arguments('--apply'), client)
        self.assertEqual(result['state'], 'already_present')
        self.assertTrue(result['complete'])
        self.assertFalse(result['target_save_attempted'] or result['persistence_verified'])
        self.assertFalse(any(c.startswith(('PROJECT ', 'DBADD', 'DBSET')) for c in client.commands))
        self.assertEqual(context.exits, 1)

    def test_rejected_creation_or_lost_reply_preserves_partial_phase_without_retry(self):
        for mode in ('rejected', 'lost_reply'):
            client = FixtureClient(); first = OSError('lost value reply')
            if mode == 'rejected':
                client.failure = lambda c: reply(600, 'Confirmation required') if c.startswith('DBADDSAFE') else None
            else:
                client.after = lambda c: first if c.startswith('DBSETSAFE') and '/Value ' in c else None
            args = arguments('--apply', '--backup-project', 'BACKUP')
            context = Connection(client)
            with self.assertRaises(NativeScheduleError) as caught:
                helper.native(args, Mock(return_value=context), None)
            if mode == 'lost_reply': self.assertIs(caught.exception.cause, first)
            evidence = helper.error_payload(caught.exception, args)[helper.EVIDENCE]
            native = evidence['native_result']
            self.assertEqual(evidence['phase'], 'apply')
            self.assertTrue(native['backup_created'] and native['backup_source_save_confirmed'])
            self.assertFalse(native['target_save_attempted'])
            self.assertEqual(len(native['levels']), 1)
            self.assertEqual(len([c for c in client.commands if c.startswith('DBADDSAFE')]), 1)
            self.assertEqual(native['levels'][0]['created'], mode == 'lost_reply')
            self.assertEqual(context.exits, 1)

    def test_first_interruption_survives_refused_evidence_and_secondary_exit(self):
        for first in (RefusedEvidence('stop'), SystemExit(29)):
            client = FixtureClient(); secondary = SystemExit('secondary close')
            client.failure = lambda c: first if c == 'PROJECT LOAD TEST' else None
            args = arguments('--apply')
            context = Connection(client, exit_error=secondary)
            with self.assertRaises(type(first)) as caught:
                helper.native(args, Mock(return_value=context), None)
            self.assertIs(caught.exception, first)
            self.assertIs(context.exit_primary, first)
            self.assertEqual(context.exits, 1)
            self.assertIs(args._thermostat_schedule_cleanup_errors[0], secondary)
            evidence = helper.error_payload(first, args)[helper.EVIDENCE]
            self.assertTrue(evidence['native_result']['target_save_confirmed'])
            self.assertFalse(evidence['native_result']['persistence_verified'])
            self.assertEqual(evidence['phase'], 'apply')
            self.assertEqual(evidence['cleanup_errors'][0]['message'], 'secondary close')
            self.assertEqual(client.commands[-1], 'PROJECT LOAD TEST')

    def test_context_suppression_cannot_turn_native_failure_into_success(self):
        first = KeyboardInterrupt('stop')
        client = FixtureClient(); client.failure = lambda c: first
        args = arguments(); context = Connection(client, suppress=True)
        with self.assertRaises(KeyboardInterrupt) as caught:
            helper.native(args, Mock(return_value=context), None)
        self.assertIs(caught.exception, first)
        self.assertEqual((context.enters, context.exits), (1, 1))

    def test_hostile_traceback_access_does_not_prevent_context_exit(self):
        class HostileTrace(KeyboardInterrupt):
            def __getattribute__(self, name):
                if name == '__traceback__': raise SystemExit('traceback getter refused')
                return super().__getattribute__(name)
            def with_traceback(self, trace): raise SystemExit('traceback method refused')
        first = HostileTrace('stop'); caught = None
        client = FixtureClient(); client.failure = lambda c: first
        context = Connection(client); args = arguments()
        try:
            helper.native(args, Mock(return_value=context), None)
        except BaseException as error:
            caught = error
        self.assertIs(caught, first)
        self.assertIs(context.exit_primary, first)
        self.assertEqual(context.exits, 1)

    def test_cleanup_failure_retains_completed_native_save_separately(self):
        for first in (OSError('close'), RefusedEvidence('close'), SystemExit(31)):
            client = FixtureClient(); args = arguments('--apply')
            context = Connection(client, exit_error=first)
            with self.assertRaises(type(first)) as caught:
                helper.native(args, Mock(return_value=context), None)
            self.assertIs(caught.exception, first)
            evidence = helper.error_payload(first, args)[helper.EVIDENCE]
            self.assertFalse(evidence['complete'])
            self.assertEqual(evidence['phase'], 'connection_cleanup')
            self.assertTrue(evidence['native_result']['complete'])
            self.assertTrue(evidence['native_result']['target_save_confirmed'])
            self.assertTrue(evidence['native_result']['persistence_verified'])
            self.assertEqual(context.exits, 1)

    def test_actual_cgate_exit_retained_cleanup_failure_remains_visible(self):
        for first in (OSError('read failed'), RefusedEvidence('stop')):
            peer = FixtureClient(); peer.failure = lambda command: first
            secondary = SystemExit('close interrupted')
            class Client(CGateClient):
                closes = 0
                def connect(self): return self
                def command(self, command): return peer.command(command)
                def close(self):
                    self.closes += 1
                    raise secondary
            context = Client('127.0.0.1'); args = arguments(); caught = None
            try:
                helper.native(args, Mock(return_value=context), None)
            except BaseException as error:
                caught = error
            if isinstance(first, Exception): self.assertIs(caught.cause, first)
            else: self.assertIs(caught, first)
            evidence = helper.error_payload(caught, args)[helper.EVIDENCE]
            self.assertEqual(evidence['phase'], 'plan')
            self.assertEqual(context.closes, 1)
            self.assertFalse(evidence['connection_exit_completed'])
            self.assertEqual(evidence['cleanup_errors'], [{'type': 'SystemExit', 'message': 'close interrupted'}])
            self.assertIs(args._thermostat_schedule_cleanup_errors[0], secondary)

    def test_connection_entry_failure_has_no_native_commands_or_second_exit(self):
        first = RefusedEvidence('greeting failed'); client = FixtureClient()
        args = arguments(); context = Connection(client, enter_error=first)
        with self.assertRaises(RefusedEvidence) as caught:
            helper.native(args, Mock(return_value=context), None)
        self.assertIs(caught.exception, first)
        self.assertEqual((context.enters, context.exits), (1, 0))
        self.assertEqual(client.commands, [])
        evidence = helper.error_payload(first, args)[helper.EVIDENCE]
        self.assertEqual(evidence['phase'], 'connection_enter')
        self.assertIsNone(evidence['native_result'])

    def test_result_export_failure_keeps_saved_receipt_and_first_error(self):
        first = RefusedEvidence('export failed'); secondary = SystemExit('second close')
        client = FixtureClient(); args = arguments('--apply')
        context = Connection(client, exit_error=secondary)
        with patch.object(NativeScheduleResult, 'as_dict', side_effect=first), self.assertRaises(RefusedEvidence) as caught:
            helper.native(args, Mock(return_value=context), None)
        self.assertIs(caught.exception, first)
        evidence = helper.error_payload(first, args)[helper.EVIDENCE]
        self.assertEqual(evidence['phase'], 'result_export')
        self.assertTrue(evidence['native_operation_completed'])
        self.assertTrue(evidence['native_result']['persistence_verified'])
        self.assertEqual(context.exits, 1)

    def test_evidence_export_failure_and_reused_args_do_not_mask_or_leak(self):
        first = RefusedEvidence('stop')
        client = FixtureClient(); client.failure = lambda c: first if c == 'PROJECT LOAD TEST' else None
        args = arguments('--apply')
        with patch.object(helper, '_dump', side_effect=SystemExit('export unavailable')), self.assertRaises(RefusedEvidence) as caught:
            helper.native(args, Mock(return_value=Connection(client)), None)
        self.assertIs(caught.exception, first)
        fallback = helper.error_payload(first, args)[helper.EVIDENCE]
        self.assertTrue(fallback['target_save_confirmed'] and fallback['evidence_export_failed'])
        self.assertEqual(helper.error_payload(KeyboardInterrupt('different'), args), {})
        args.apply = False
        self.invoke(args, FixtureClient())
        self.assertEqual(helper.error_payload(first, args), {})

    def test_output_failure_retains_confirmed_save_and_first_error(self):
        for first in (OSError('stdout failed'), RefusedEvidence('output stop')):
            args = arguments('--apply'); client = FixtureClient()
            (result, _), context, _ = self.invoke(args, client)
            before = list(client.commands)
            self.assertTrue(result['persistence_verified'])
            evidence = helper.record_output_error(args, first)[helper.EVIDENCE]
            self.assertIs(args._thermostat_schedule_error, first)
            self.assertEqual(evidence['phase'], 'output')
            self.assertFalse(evidence['complete'])
            self.assertTrue(evidence['native_result']['target_save_confirmed'])
            self.assertTrue(evidence['native_result']['persistence_verified'])
            self.assertEqual(client.commands, before)
            self.assertEqual(context.exits, 1)
            second = SystemExit('second output failure')
            self.assertEqual(helper.record_output_error(args, second), helper.error_payload(first, args))
            self.assertIs(args._thermostat_schedule_error, first)
            self.assertEqual(helper.error_payload(second, args), {})
            evidence['native_result'].clear()
            self.assertTrue(helper.error_payload(first, args)[helper.EVIDENCE]['native_result']['target_save_confirmed'])

    def test_output_failure_does_not_adopt_other_or_reused_invocation_state(self):
        args = arguments('--apply')
        self.invoke(args, FixtureClient())
        args.action = 'other'
        self.assertEqual(helper.record_output_error(args, OSError('unrelated')), {})
        args.action = 'thermostat-schedule-levels'; args.exclusive_project = False
        with self.assertRaises(ValueError) as caught:
            helper.native(args, Mock(side_effect=AssertionError('no I/O')), None)
        first = caught.exception
        payload = helper.record_output_error(args, OSError('later output error'))
        self.assertIs(args._thermostat_schedule_error, first)
        self.assertEqual(payload[helper.EVIDENCE]['phase'], 'cli_preflight')
        self.assertIsNone(payload[helper.EVIDENCE]['native_result'])
        fresh = arguments()
        self.assertEqual(helper.record_output_error(fresh, OSError('not executed')), {})

    def test_output_error_export_refusal_preserves_save_summary(self):
        args = arguments('--apply'); self.invoke(args, FixtureClient())
        first = RefusedEvidence('output stop')
        with patch.object(helper, '_dump', side_effect=SystemExit('second export failure')):
            payload = helper.record_output_error(args, first)
        self.assertIs(args._thermostat_schedule_error, first)
        evidence = payload[helper.EVIDENCE]
        self.assertTrue(evidence['evidence_export_failed'] and evidence['target_save_confirmed'])
        self.assertTrue(evidence['persistence_verified'])
        self.assertEqual(evidence['phase'], 'output')

    def test_first_capture_interrupt_stops_before_later_result_export(self):
        for later in ('success', 'second_interrupt'):
            first = RefusedEvidence('capture interrupted')
            secondary = SystemExit('secondary capture failure')
            args = arguments('--apply'); client = FixtureClient(); context = Connection(client)
            original = helper._decode
            calls = 0
            def decode(text):
                nonlocal calls
                calls += 1
                if calls == 1: raise first
                if later == 'second_interrupt': raise secondary
                return original(text)
            with patch.object(helper, '_decode', side_effect=decode), \
                    patch.object(NativeScheduleResult, 'as_dict', side_effect=SystemExit('must not export')) as export, \
                    self.assertRaises(RefusedEvidence) as caught:
                helper.native(args, Mock(return_value=context), None)
            self.assertIs(caught.exception, first)
            export.assert_not_called()
            evidence = helper.error_payload(first, args)[helper.EVIDENCE]
            self.assertEqual(evidence['phase'], 'native_evidence')
            native = json.loads(evidence['native_result_document'])
            self.assertTrue(native['target_save_confirmed'] and native['persistence_verified'])
            self.assertEqual(context.exits, 1)

    def test_first_success_evidence_export_interrupt_retains_saved_summary(self):
        first = RefusedEvidence('evidence interrupted'); secondary = SystemExit('secondary evidence failure')
        args = arguments('--apply'); client = FixtureClient(); context = Connection(client)
        original = helper._dump
        calls = 0
        def dump(value):
            nonlocal calls
            calls += 1
            if calls == 1: return original(value)  # Native result validation.
            if calls == 2: raise first  # First failure at success evidence export.
            raise secondary
        with patch.object(helper, '_dump', side_effect=dump), self.assertRaises(RefusedEvidence) as caught:
            helper.native(args, Mock(return_value=context), None)
        self.assertIs(caught.exception, first)
        evidence = helper.error_payload(first, args)[helper.EVIDENCE]
        self.assertEqual(evidence['phase'], 'evidence_export')
        self.assertTrue(evidence['target_save_confirmed'] and evidence['persistence_verified'])
        self.assertEqual(context.exits, 1)


if __name__ == '__main__':
    unittest.main()
